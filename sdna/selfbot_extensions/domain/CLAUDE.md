# selfbot/domain

Pure business objects, no external dependencies. `models.py` = the scheduled-bot
side; `procedure.py` = the SDK-pipeline side (and where the three laws are
enforced structurally); `automation.py` + the two `*_codegen.py` modules compile
schemas into Python.

Nothing here may import from `application/` or `infrastructure/`.
