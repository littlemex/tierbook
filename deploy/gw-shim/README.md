# gw-shim

An OpenAI chat-completions face over the billing gateway's Anthropic surface.

## Why it exists

A two-arm comparison needs the arms to differ in one thing. The first attempt at a metered arm pointed the
agent's **Anthropic** provider at the gateway while the self-hosted arm used its **OpenAI-compatible** provider,
so the arms differed in the client library as well as in the model. The consequence was invisible in the
outcomes and obvious in the request sizes: the metered arm's calls carried 3, 6, 6, 6, 3666, 3815, 7, 7 prompt
tokens across a run -- no accumulating history and no tool schemas -- against the self-hosted arm's cache reads
climbing 6,336 to 23,232 on comparable work. 54 times fewer tokens over 24 tasks.

The gateway was not at fault. A five-message array sent to it directly reported 2,443 input tokens, and the
agent's own session store held the full conversations. The loss was in the provider path.

With this in front, both arms use `@ai-sdk/openai-compatible` and only the model and endpoint change. Verified
after deployment: the first call carried 11 tool schemas and 7,997 input tokens, the second 4 messages and
8,074, with one tool result paired to one call.

## What it logs

Every forwarded request, to `/data/gw-shim/requests.jsonl` on the shared volume: message count, content bytes,
tool count, tool-result count, assistant tool calls, and the usage the gateway returned. The earlier failure was
undetectable from outcomes and immediate from these, and a translator nobody can audit is a second place for the
same failure to hide.

## What it refuses

Any request field it does not translate, by name. A parameter dropped in translation changes the candidate,
which is the defect it exists to prevent, so `response_format`, `logprobs`, `top_logprobs`, `n` and `seed`
return a 400 rather than being ignored.

## Deploying

The Python file is embedded in a ConfigMap by the deploy step, so the pod needs no image build:

    kubectl -n <ns> create secret generic gw-shim-key --from-literal=key="$GATEWAY_API_KEY"
    kubectl -n <ns> apply -f deploy/gw-shim/gw-shim.yaml

Point an agent at `http://gw-shim:8000/v1` with any api key; the real one lives in the secret.
