"""Hard USD spend cap for every CHI-Bench model call (agent + judge + simulators).

v2 (2026-10-28) -- reconciled accounting.

What changed from v1, and why:

* **Real prices.** v1 priced every model at deliberately high ceilings and matched
  by prefix, so ``gpt-5.6-luna`` was billed as ``gpt-5`` at USD 15/120 per 1M.
  v2 reads a pinned price table (``--prices``) that carries verified list prices
  per model plus cache read/write rates. Unknown models are denied, never guessed.

* **Token-based reservation.** v1 reserved ``len(body bytes)`` as if every byte
  were a token, roughly 3.5x too much, which is what pushed a USD 40 ledger into
  a 402 while real spend was under USD 1. v2 counts tokens with a tokenizer and a
  safety margin, and still reserves the worst case for output.

* **Cache-aware settlement.** v1 charged every input token at the full input rate
  and added ``cache_read_input_tokens`` on top of ``input_tokens``, double counting
  OpenAI usage where the total already includes the cached part. v2 applies the
  cache discount only when the provider actually reports cache hits, and treats
  Anthropic (exclusive) and OpenAI (inclusive) usage shapes correctly.

* **Append-only reconciliation.** Historical spend is never rewritten. Corrections
  are entries in ``adjustments`` (each with a reason and its evidence) and the gross
  figure stays in the ledger as ``gross_spent_usd``. Spend counted against the cap is
  ``spent + sum(adjustments)``.

Safety properties kept from v1: a single lock, worst-case reservation before
forwarding, admission only when ``committed + reserve <= cap``, settle-to-usage
capped by the reservation, atomic persistence, in-flight reservations converted to
spend on restart, and no credential in logs.
"""
from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MAX_CAP_USD = 45.0
MAX_OUTPUT_CLAMP = 16384
# Safety margin applied to the tokenizer estimate before it becomes a reservation.
TOKEN_MARGIN = 1.10
# Fallback characters-per-token when no tokenizer is importable (conservative).
CHARS_PER_TOKEN = 3.0

# USD per 1M tokens: (input, output, cache_read, cache_write).
# These are *ceilings* for models without a verified entry, so an unconfigured
# deployment still fails expensive-but-safe. The real run passes --prices.
DEFAULT_PRICES = {
    "claude-opus": (15.0, 75.0, 1.5, 18.75),
    "claude-sonnet": (6.0, 30.0, 0.6, 7.5),
    "claude-haiku": (2.0, 10.0, 0.2, 2.5),
    "gpt-5": (15.0, 120.0, 1.5, 15.0),
    "gpt-4.1": (5.0, 20.0, 0.5, 5.0),
    "gpt-4o": (5.0, 20.0, 0.5, 5.0),
    "o3": (15.0, 60.0, 1.5, 15.0),
    "o4": (5.0, 20.0, 0.5, 5.0),
}
UPSTREAMS = {"anthropic": "https://api.anthropic.com", "openai": "https://api.openai.com"}
AUTH_HEADERS = {"authorization", "x-api-key", "anthropic-api-key", "api-key"}
HOP = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding"}

try:  # exact counts when available; the fallback stays conservative
    import tiktoken

    _ENC = tiktoken.get_encoding("o200k_base")
except Exception:  # pragma: no cover - exercised only without tiktoken
    _ENC = None


class BudgetDenied(RuntimeError):
    pass


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 256


def normalize_price(value) -> dict:
    """Accept (input, output), (input, output, cache_read, cache_write) or a dict."""
    if isinstance(value, dict):
        pin = float(value["input"])
        pout = float(value["output"])
        return {
            "input": pin,
            "output": pout,
            "cache_read": float(value.get("cache_read", pin)),
            "cache_write": float(value.get("cache_write", pin)),
        }
    seq = tuple(value)
    if len(seq) == 2:
        pin, pout = (float(x) for x in seq)
        return {"input": pin, "output": pout, "cache_read": pin, "cache_write": pin}
    if len(seq) == 4:
        pin, pout, cr, cw = (float(x) for x in seq)
        return {"input": pin, "output": pout, "cache_read": cr, "cache_write": cw}
    raise ValueError(f"price must have 2 or 4 values, got {len(seq)}")


def price_for(model: str, prices: dict) -> dict:
    """Longest matching entry wins; exact id, bare id and prefix all match."""
    m = (model or "").lower().strip()
    bare = m.rsplit("/", 1)[-1]
    best = None
    for key in prices:
        k = key.lower()
        if m == k or bare == k or m.startswith(k) or bare.startswith(k) or f"/{k}" in m:
            if best is None or len(k) > len(best):
                best = k
    if best is None:
        raise BudgetDenied("unpriced_model")
    return prices[best]


def estimate_input_tokens(raw: bytes) -> int:
    """Upper-ish bound on prompt tokens for a request body.

    The tokenizer gives the real count for OpenAI models and a close estimate for
    Anthropic ones; the margin and the byte ceiling keep the result conservative.
    """
    text = raw.decode("utf-8", "replace")
    if _ENC is not None:
        try:
            n = len(_ENC.encode(text, disallowed_special=()))
        except Exception:  # pragma: no cover
            n = math.ceil(len(text) / CHARS_PER_TOKEN)
    else:  # pragma: no cover
        n = math.ceil(len(text) / CHARS_PER_TOKEN)
    return int(math.ceil(min(max(n * TOKEN_MARGIN, n + 8), len(raw))))


def usage_cost(usage: dict, price: dict) -> float:
    """USD for one provider-reported usage block.

    Anthropic reports ``input_tokens`` *excluding* cache traffic; OpenAI reports a
    total that *includes* the cached part. Discounting only when the provider
    reports hits keeps the estimate honest in both shapes.
    """
    pin = price["input"]
    pout = price["output"]
    pcr = price["cache_read"]
    pcw = price["cache_write"]

    if "cache_read_input_tokens" in usage or "cache_creation_input_tokens" in usage:
        uncached = float(usage.get("input_tokens", 0) or 0)
        read = float(usage.get("cache_read_input_tokens", 0) or 0)
        write = float(usage.get("cache_creation_input_tokens", 0) or 0)
        out = float(usage.get("output_tokens", 0) or 0)
        return (uncached * pin + read * pcr + write * pcw + out * pout) / 1e6

    total_in = float(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    out = float(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    cached = float(details.get("cached_tokens", 0) or 0) if isinstance(details, dict) else 0.0
    # Codex's own session rollup names the field differently; accept it too.
    cached = max(cached, float(usage.get("cached_input_tokens", 0) or 0))
    cached = min(cached, total_in)
    return ((total_in - cached) * pin + cached * pcr + out * pout) / 1e6


class Ledger:
    def __init__(self, cap_usd: float, path: Path | None = None, prices: dict | None = None):
        if not 0 < cap_usd <= MAX_CAP_USD:
            raise ValueError(f"cap must be in (0, {MAX_CAP_USD}]")
        self.cap, self.path = float(cap_usd), path
        self.prices = {k: normalize_price(v) for k, v in (prices or DEFAULT_PRICES).items()}
        self.lock = threading.Lock()
        self.spent = 0.0
        self.adjustments: list[dict] = []
        self.reserved: dict[str, float] = {}
        self.calls = self.denied = 0
        self.settle_capped = 0
        self.max_inflight_reserved = 0.0
        self.max_committed = 0.0
        if path and path.exists():
            d = json.loads(path.read_text())
            if d.get("cap") != self.cap:
                raise ValueError("ledger cap mismatch")
            # Anything that was in flight when we stopped counts as fully spent.
            self.spent = d["spent"] + sum(d.get("reserved", {}).values())
            self.adjustments = [a for a in (d.get("adjustments") or []) if isinstance(a, dict)]
            self.calls, self.denied = d.get("calls", 0), d.get("denied", 0)
            self.settle_capped = d.get("settle_capped", 0)
            self._persist()

    @property
    def adjustments_total(self) -> float:
        return sum(float(a.get("usd", 0.0)) for a in self.adjustments)

    @property
    def effective_spent(self) -> float:
        return self.spent + self.adjustments_total

    def _payload(self) -> dict:
        return {
            "cap": self.cap,
            "spent": self.spent,
            "adjustments": self.adjustments,
            "reserved": self.reserved,
            "calls": self.calls,
            "denied": self.denied,
            "settle_capped": self.settle_capped,
        }

    def _persist(self):
        if self.path:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._payload()))
            os.replace(tmp, self.path)

    def reserve(self, model: str, raw: bytes, max_out: int) -> tuple[str, float]:
        price = price_for(model, self.prices)
        in_ub = estimate_input_tokens(raw)
        amount = (in_ub * price["input"] + max_out * price["output"]) / 1e6
        with self.lock:
            committed = self.effective_spent + sum(self.reserved.values())
            if committed + amount > self.cap + 1e-12:
                self.denied += 1
                self._persist()
                raise BudgetDenied("budget_exhausted")
            rid = uuid.uuid4().hex
            self.reserved[rid] = amount
            self.calls += 1
            self.max_inflight_reserved = max(self.max_inflight_reserved, sum(self.reserved.values()))
            self.max_committed = max(self.max_committed, self.effective_spent + sum(self.reserved.values()))
            self._persist()
            return rid, amount

    def settle(self, rid: str, model: str, usage: dict | None):
        with self.lock:
            amount = self.reserved.pop(rid, None)
            if amount is None:
                return 0.0
            actual = amount
            if usage:
                try:
                    actual = usage_cost(usage, price_for(model, self.prices))
                except (TypeError, ValueError, BudgetDenied):
                    actual = amount
                # A reservation is a ceiling for one call; flag any overshoot instead
                # of silently letting a single call pass the cap.
                if actual > amount:
                    self.settle_capped += 1
                    actual = amount
            self.spent += actual
            self._persist()
            return actual

    def add_adjustment(self, usd: float, reason: str, evidence) -> dict:
        """Append an audited correction. Never rewrites, never deletes."""
        entry = {"usd": round(float(usd), 6), "reason": reason, "evidence": evidence,
                 "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        with self.lock:
            self.adjustments.append(entry)
            self._persist()
        return entry

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "cap_usd": self.cap,
                "spent_usd": round(self.effective_spent, 6),
                "gross_spent_usd": round(self.spent, 6),
                "adjustments_usd": round(self.adjustments_total, 6),
                "reserved_usd": round(sum(self.reserved.values()), 6),
                "inflight": len(self.reserved),
                "calls": self.calls,
                "denied": self.denied,
                "settle_capped": self.settle_capped,
            }


def clamp_request(body: dict) -> int:
    """Ensure an explicit output bound exists and is <= MAX_OUTPUT_CLAMP; return it."""
    for key in ("max_tokens", "max_output_tokens", "max_completion_tokens"):
        if key in body:
            v = int(body[key] or MAX_OUTPUT_CLAMP)
            body[key] = min(v, MAX_OUTPUT_CLAMP)
            return body[key]
    body["max_tokens" if "messages" in body and "input" not in body else "max_output_tokens"] = MAX_OUTPUT_CLAMP
    return MAX_OUTPUT_CLAMP


def extract_usage(raw: bytes) -> dict | None:
    """Usage from a JSON body or the last usage-bearing SSE event (Anthropic/OpenAI)."""
    try:
        d = json.loads(raw)
        return d.get("usage") or (d.get("response") or {}).get("usage")
    except ValueError:
        pass
    merged: dict = {}
    for line in raw.splitlines():
        if not line.startswith(b"data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except ValueError:
            continue
        for u in (ev.get("usage"), (ev.get("message") or {}).get("usage"), (ev.get("response") or {}).get("usage")):
            if isinstance(u, dict):
                for k, v in u.items():
                    if isinstance(v, int):
                        merged[k] = v
                    elif isinstance(v, dict) and k.endswith("_details"):
                        merged[k] = {kk: vv for kk, vv in v.items() if isinstance(vv, int)}
    return merged or None


def make_handler(ledger: Ledger, upstreams: dict, keys: dict | None = None):
    keys = keys or {}
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a):  # never log headers or bodies
            pass

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code); self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            if self.path == "/budget":
                return self._send(200, ledger.snapshot())
            return self._forward(None)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("content-length") or 0))
            return self._forward(raw)

        def _forward(self, raw):
            prefix, _, rest = self.path.lstrip("/").partition("/")
            base = upstreams.get(prefix)
            if not base:
                return self._send(404, {"error": "unknown_upstream_prefix"})
            rid = model = None
            if raw is not None:
                try:
                    body = json.loads(raw or b"{}")
                    model = body.get("model", "")
                    max_out = clamp_request(body)
                    raw = json.dumps(body).encode()
                    rid, _ = ledger.reserve(model, raw, max_out)
                except BudgetDenied as exc:
                    return self._send(402, {"type": "error", "error": {"type": "budget_exhausted", "message": str(exc)}})
                except (ValueError, AttributeError):
                    return self._send(400, {"error": "unmetered_request_body"})
            u = urlsplit(base)
            conn = (http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection)(u.netloc, timeout=900)
            data, resp, err = b"", None, False
            try:
                hdrs = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
                # Key injection: clients hold only a dummy key, so any route that
                # bypasses this proxy fails authentication instead of spending.
                if keys.get(prefix):
                    hdrs = {k: v for k, v in hdrs.items() if k.lower() not in AUTH_HEADERS}
                    if prefix == "anthropic":
                        hdrs["x-api-key"] = keys[prefix]
                    else:
                        hdrs["Authorization"] = "Bearer " + keys[prefix]
                conn.request(self.command, (u.path.rstrip("/") + "/" + rest), body=raw, headers=hdrs)
                resp = conn.getresponse()
                data = resp.read()
            except OSError:
                err = True
            finally:
                conn.close()
                # Settle before replying so the ledger is final when the caller sees the result.
                if rid is not None:
                    ledger.settle(rid, model, extract_usage(data) if data else None)
            if err:
                return self._send(502, {"error": "upstream_failed"})
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
    return H


def load_prices(path: Path | None) -> dict | None:
    if not path:
        return None
    d = json.loads(Path(path).read_text())
    raw = d.get("models", d) if isinstance(d, dict) else d
    return {k: normalize_price(v) for k, v in raw.items() if not k.startswith("_")}


def serve(cap: float, ledger_path: Path, port: int, upstreams: dict | None = None,
          prices_file: Path | None = None, bind: str = "127.0.0.1", keys_file: Path | None = None):
    prices = load_prices(prices_file)
    ledger = Ledger(cap, ledger_path, prices)
    srv = ProxyServer((bind, port), make_handler(ledger, upstreams or UPSTREAMS, load_keys(keys_file)))
    return srv, ledger


def load_keys(path):
    """Provider keys held only by the proxy (file must be private: mode 600)."""
    if not path:
        return {}
    path = Path(path)
    if path.stat().st_mode & 0o077:
        raise ValueError("keys file must not be group/world readable")
    d = json.loads(path.read_text())
    return {k: v for k, v in d.items() if k in UPSTREAMS and isinstance(v, str) and v}


def require_budget_proxy(url: str, max_cap: float = MAX_CAP_USD) -> dict:
    """Runner admission: proxy is up, cap <= max_cap, and headroom remains."""
    u = urlsplit(url)
    conn = http.client.HTTPConnection(u.netloc, timeout=10)
    try:
        conn.request("GET", "/budget"); r = conn.getresponse(); d = json.loads(r.read())
    except (OSError, ValueError):
        raise BudgetDenied("budget_proxy_unreachable") from None
    finally:
        conn.close()
    if r.status != 200 or not 0 < float(d.get("cap_usd", 0)) <= max_cap:
        raise BudgetDenied("budget_proxy_cap_invalid")
    if d["spent_usd"] + d["reserved_usd"] >= d["cap_usd"]:
        raise BudgetDenied("budget_exhausted")
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="chi_budget_proxy")
    ap.add_argument("--cap-usd", type=float, default=MAX_CAP_USD)
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--port", type=int, default=18045)
    ap.add_argument("--prices", type=Path)
    ap.add_argument("--keys-file", type=Path, help="JSON {openai,anthropic} keys injected upstream; clients get dummies")
    ap.add_argument("--bind", default="127.0.0.1", help="e.g. docker bridge IP so containers can reach it")
    a = ap.parse_args(argv)
    srv, ledger = serve(a.cap_usd, a.ledger, a.port, prices_file=a.prices, bind=a.bind, keys_file=a.keys_file)
    print(json.dumps({"listening": f"{a.bind}:{a.port}", **ledger.snapshot()}), flush=True)
    srv.serve_forever()
    return 0


ROUTED_VARS = ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "CHI_BENCH_JUDGE_BASE_URL", "HG_JUDGE_ANTHROPIC_BASE_URL")
# With key injection, real provider keys must not be visible to clients/containers.
REAL_KEY_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
# Credentials for providers the proxy does not meter; any of them would be an uncapped path.
UNMETERED_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "GEMINI_API_KEY", "GROK_API_KEY", "XAI_API_KEY", "OPENROUTER_API_KEY")


def _dotenv_keys(path):
    """Return {key: value} from a dotenv file. Values are only compared, never logged."""
    out = {}
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.replace("export ", "", 1).strip()
        out[k] = v.strip().strip("'\"")
    return out


def routing_problems(env, base, dotenv_path=None):
    """Names (never values) of variables that would bypass the proxy, considering a dotenv override."""
    eff = dict(env)
    if dotenv_path:
        eff.update(_dotenv_keys(dotenv_path))  # chi-bench loads .env with override=True
    prefix = base.rstrip("/") + "/"
    probs = [f"{v} must route through the budget proxy" for v in ROUTED_VARS if not eff.get(v, "").startswith(prefix)]
    probs += [f"{v} is set (unmetered provider path)" for v in UNMETERED_VARS if eff.get(v)]
    probs += [f"{v} holds a real provider key (must be a proxy dummy)" for v in REAL_KEY_VARS if eff.get(v, "").startswith("sk-")]
    return probs


if __name__ == "__main__":
    raise SystemExit(main())
