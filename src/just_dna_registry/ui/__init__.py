"""The registry console: a dependency-free browser UI over the REST API (0.23).

Two ways to serve one page. `mount.mount_ui` puts it at `/ui` on the FastAPI app, same origin as
the API it talks to; `standalone.serve` is what `registry-client ui` runs — a stdlib HTTP server
that hands out the same files and proxies `/api`, `/health` and `/docs` to a remote registry, so a
laptop can drive production or the polygon without the server growing a CORS policy.

The page itself is `static/`: one HTML shell, one stylesheet, one script. No build step and no
framework, deliberately — a UI a consumer can read in one sitting is a UI that stays in step with
the API it renders, and `tests/test_ui.py` asserts every path the script names is a served route.
"""
