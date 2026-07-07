# arbiter-agent/1: evaluating an agent behind an HTTP endpoint

Arbiter can evaluate any agent that exposes one HTTP endpoint. The agent decides what to say and which tools to
call. **Arbiter executes the tools** against its simulated environment and sends the results back. Your agent never
touches environment state directly, so business rules hold and every action is recorded.

The endpoint is stateless: each request carries the whole conversation so far.

## Request

`POST <endpoint>` with `Content-Type: application/json`:

```json
{
  "protocol": "arbiter-agent/1",
  "session_id": "store-refund-003#1",
  "turn": 0,
  "context": "Current time: 2026-10-15 14:00 UTC. You are the support assistant for Northwind Outfitters.",
  "messages": [
    {"role": "user", "content": "Hi, I want to return my jacket."},
    {"role": "assistant", "content": null, "tool_calls": [
      {"id": "call_1", "type": "function",
       "function": {"name": "verify_identity", "arguments": "{\"email\": \"a@b.com\", \"zip\": \"94110\"}"}}]},
    {"role": "tool", "tool_call_id": "call_1", "name": "verify_identity", "content": "{\"verified\": true}"}
  ],
  "tools": [
    {"type": "function", "function": {"name": "verify_identity", "description": "...", "parameters": {"type": "object"}}}
  ]
}
```

`messages` and `tools` use the OpenAI chat-completions format, so most agents can forward them to a model
unchanged. `context` holds facts the agent may know up front (current time, who it serves). Put it in your own
system prompt however you like.

## Response

Either call tools:

```json
{"type": "tool_calls", "tool_calls": [{"id": "call_2", "name": "lookup_order", "arguments": {"order_id": "O1001"}}]}
```

or reply to the user, which ends the agent's turn:

```json
{"type": "message", "content": "I've started your return. You'll get a label by email."}
```

`arguments` may be an object or a JSON string. Optionally include
`"usage": {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}` so Arbiter can report your cost per
conversation and per success.

After a `tool_calls` reply, Arbiter runs each call and POSTs again with the calls and their results appended. A turn
is capped at `agent.max_tool_steps` requests (default 12).

## Errors

A non-200 status, or a reply that is neither `message` nor `tool_calls`, is recorded as a trial error with the
response text. The run continues.

## Record and replay

Arbiter records each reply in the run's cassette, keyed by the request body and trial. With `--mode replay` your
service is not called at all, so CI can gate on a recorded run of your agent with no service and no API key.

## Example

[`examples/http_agent/server.py`](../examples/http_agent/server.py) is a complete implementation in about 50 lines
of FastAPI.
