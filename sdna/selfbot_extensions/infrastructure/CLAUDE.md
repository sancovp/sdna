# selfbot/infrastructure

Adapters implementing the domain's protocols. Browser driving
(`procedure_runtime.py`), trace capture (`recorder.py`), persistence
(`file_storage.py`, `procedure_storage.py`), screens, scheduling, queue.

Swapping the browser (Playwright -> CloakBrowser) is a change HERE and nowhere
else — that is what the tiny `PageDriver` protocol buys.
