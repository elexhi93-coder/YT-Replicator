"""
ui.pages — one module per Wave 4 page (U16-U22).

Each page is a thin layer over services that are already tested. The rule
that keeps these thin: **a view decides nothing.** It gathers context,
delegates to a module's `api`, and renders. Any question with a right answer
("is this token healthy?", "may this user connect a channel?") is answered by
the module that owns it, so the answer cannot drift between the page and the
worker.
"""
