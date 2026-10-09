# selfbot/application

Use cases. Every class here takes its dependencies injected and knows nothing
about Xvfb, Playwright, or the filesystem. `sdk_builder.py` drives the
explore->compile pipeline; `immune.py` keeps the compiled SDK honest.
