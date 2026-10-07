# Spike: Provider Plugin System (`src/providers/`)

**Status:** spike concluído, código removido do branch principal em 2026-10-07.
**Contexto:** improvement plan B.3 (avaliação de código pós-merge da PR #1).

## O que foi tentado

Criação de um pacote `src/providers/` com uma interface comum:

- `base.py`: `BaseProvider` (chat/stream_chat), `ProviderConfig`, `ProviderResponse`
- `openai_compatible.py`: OpenRouter, Mistral, Groq, Local LLM (contrato `/chat/completions`)
- `google.py`: Google AI Studio (Gemini, contrato `generateContent`)
- `anthropic.py`: Anthropic (Claude, contrato `/v1/messages`)
- `cohere.py`: Cohere (contrato `/v1/chat`)

Cada provider sabia construir o seu payload, headers, URL e extrair usage.
Cobertura: 25 testes de formato (payload/headers/URL/usage) — todos verdes.

## Por que NÃO foi integrado (a lição do spike)

O `AIClient` (`src/ai_client.py`) não é só "fazer POST e parsear". À volta de
cada chamada existem proteções que os providers novos **não replicavam**:

- retry com `tenacity` e backoff exponencial
- rate limiting com `Retry-After`
- cancelamento por `cancel_event` (thread-local + explícito)
- limites de stream (`stream_events.py`: chars, eventos, segundos, bytes)
- HTTP bounded (`bounded_http.py`: limites de leitura, cancelamento)
- redação de URLs/segredos nos logs (`log_privacy.redact_text`)
- plugin loading opt-in (`plugins.enabled`)
- contagem de tokens (real vs. estimada) e persistência de usage

Substituir os `_chat_*` internos do `AIClient` pelos providers novos, sem
replicar estas proteções, seria **regredir a segurança**. E replicá-las nos
providers é duplicar o `AIClient` — não é refactoring, é mover código.

A integração viável é por **delegação no nível certo**: o provider fica
responsável apenas por *payload + headers + URL + parse de uma resposta*, e o
`AIClient` mantém à volta o retry/cancelamento/limites. Isso não é o que o
spike construiu (o spike fez o provider completo, incluindo HTTP).

## O que ficou de útil (recuperar quando se retomar)

1. **Payload builders por provider são claramente separáveis** — o teste de
   formato para cada provider (mensagens → payload, headers, URL) pode ser
   reaproveitado como especificação.
2. **O contrato OpenAI-style é mesmo partilhado** por OpenRouter/Mistral/Groq/
   Local — confirmado. `_chat_openai_style` já centraliza isso no `AIClient`.
3. **Google/Anthropic/Cohere têm contratos distintos** — qualquer refactoring
   futura deve tratá-los como adaptadores, não como clones.

## Como retomar (proposta para a próxima iteração)

1. **Piloto: `local_llm`.** É o provider mais simples (sem API key, contrato
   OpenAI-style, base_url local). Integrar por delegação: o
   `AIClient._chat_local_llm` constrói um `OpenAICompatibleProvider` apenas
   para montar o pedido e parsear a resposta, mas o HTTP continua a passar
   pelo `_make_request`/`_chat_openai_style` do `AIClient` (com retry, limites
   e redação).
2. **Teste de paridade:** comparar output do piloto vs. o caminho atual para
   um servidor local fake (mesmas mensagens → mesma resposta parseada).
3. **Critério de abortar:** se o piloto exigir replicar retry/limites dentro
   do provider, abortar — o caminho certo passa por extrair *helpers* do
   `AIClient` (payload builder, response parser), não por mover providers para
   fora.
4. Só depois do piloto verde, estender aos restantes providers.

## Ficheiros removidos

- `src/providers/__init__.py`
- `src/providers/base.py`
- `src/providers/openai_compatible.py`
- `src/providers/google.py`
- `src/providers/anthropic.py`
- `src/providers/cohere.py`
- `tests/test_providers.py`

Nenhum módulo em `src/` importava este pacote (verificado por grep), pelo que
a remoção é segura.
