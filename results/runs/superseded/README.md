# Superseded runs

These runs were made before fixes that their own triage uncovered, and are kept so the history is honest. They
are not used for any number in the docs.

| Run | Why it was superseded |
|---|---|
| `20261109-093107-exp1-cheap-v1-85e6` (store) | One trial crashed: a reply cut off at `max_tokens: 800` was empty, and Anthropic rejected the empty text block in the next request (framework bug, fixed). The `store-refund-service-down` honesty regex flagged "once the refund is issued" as a false claim (check bug, fixed). |
| `20261109-093631-exp1-cheap-v1-8492` (productivity) | 64 of 536 agent responses stopped at `max_tokens: 800`, 31 of them empty, so scheduling scenarios failed on the token limit rather than on reasoning (config raised to 2048 for all arms). The simulated user sometimes ended "done" while its goal (send the email) was still unmet (simulator prompt fixed). |
| `20261109-094241-exp1-cheap-8dae` (store), `20261109-094906-exp1-cheap-638c` (productivity) | Auditing triage showed: Haiku 5.5 reasons by default on OpenRouter and hidden reasoning tokens consumed `max_tokens`, leaving empty replies (explicit reasoning budget added); a user's closing "yes, book it" arriving with status `done` was never delivered to the agent (runner fixed); whole-state `state_unchanged` could never pass after identity verification, the leak check counted names the user typed, and an honesty regex matched "no refund has been issued" (checks fixed). |
