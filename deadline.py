"""A hard time limit for one Gemini call.

The google-genai timeout is not a hard limit in practice: with it set to 75 s, document readings answered after
105 s and 148 s (saved readings, 25 Nov). So the call runs in its own thread and we stop waiting at the deadline.
A late answer is ignored; the thread ends by itself when Gemini finally answers (daemon: it never blocks exit).
Used by assistant.py (the chat) and paperwork/extract.py (reading documents, document questions).
"""
import threading


class CallTimedOut(Exception):
    """Raised when the call gave no answer within its time limit."""


def call_with_deadline(fn, seconds):
    """fn()'s result, or CallTimedOut if it takes longer than `seconds`. fn's own errors are raised as they are."""
    outcome = {}

    def run():
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # handed to the caller below, in the caller's thread
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(max(0.0, seconds))
    if worker.is_alive():
        raise CallTimedOut(f"no answer within {seconds:.0f} s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]
