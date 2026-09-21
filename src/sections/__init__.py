"""Each section runs inside its own try/except and returns data or an error object (rule 5)."""


def run(build_fn, ctx):
    try:
        return build_fn(ctx)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
