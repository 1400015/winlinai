# Correção da sonda Get-Service — 9 de outubro de 2026

A sonda serializava objetos `ServiceController` completos com profundidade 10, apesar de o chat consumir apenas quatro campos. A conversão podia consultar propriedades de serviços relacionados e percorrer dependências desnecessárias. O utilizador comunicou um inventário direto de 301 serviços em cerca de dois segundos e um timeout de 45 segundos na experiência com JSON; essas medições Windows não foram repetidas neste ambiente.

## Alteração isolada

A branch `fix/get-service-json-projection` parte de `92b8833`. Apenas `Get-Service`, incluindo a consulta com `-Name`, projeta `Name`, `DisplayName`, `Status` e `StartType` antes de `ConvertTo-Json`. Os dois enums passam a texto e a profundidade do JSON projetado é 2. A validação dos argumentos, encoding, prazo de 30 segundos e limite de 1 MiB continuam a aplicar-se.

O inventário da sonda conserva todos os elementos; o limite de 50 serviços apresentados pelo chat mantém-se. A entrega consulta o sistema e não altera serviços nem instala pacotes. As alterações Qt e de autorização de edição existentes noutra branch local não pertencem a esta entrega.

## Verificação executada

- PowerShell 7.6.6 em Linux, com objetos de teste e getters contados: os dois testes falharam antes da correção, com 228 acessos a dependências na lista de 57 objetos e quatro na consulta individual. Depois da correção há zero acessos, os 57 elementos mantêm-se e os campos Unicode e enums textuais passam.
- Python 3.12: 109 testes relacionados descobertos, 108 passaram e o teste nativo Windows foi omitido por estar em Linux. A normalização E2E Qt passou separadamente; os 29 testes da política PowerShell também passaram.
- Python 3.8: 106 testes relacionados passaram. Ruff, byte-compilation, diff-check e mypy do módulo alterado para os alvos Linux e Windows passaram.

Esta prova portátil verifica a fronteira de serialização. Não comprova tempos ou resultados de `Get-Service` em Windows.

## Aceitação Windows comunicada

O utilizador comunicou uma execução do Grok em Windows PowerShell **5.1.26100.9549** sobre o patch aplicado limpo a `92b8833`. Os quatro módulos de teste totalizaram **52 testes, todos aprovados**. A consulta direta devolveu **301 serviços em 1,12 s**; a sonda JSON devolveu os mesmos **301 serviços em 1,38 s**. A consulta individual coincidiu no nome e no texto apresentado. O fixture confirmou zero leituras das dependências, incluindo Unicode.

Esta execução fecha o critério de aceitação nativa da entrega, com evidência externa comunicada pelo utilizador. Não foi repetida no ambiente Linux desta sessão. O patch continua local, sem publicação no GitHub. A prova necessária para avançar no plano foi satisfeita; o instalador continua a exigir a sua própria compilação e aceitação.

### Repetir a aceitação

No checkout desta branch, executar em Windows, com o ambiente do projeto já disponível:

```powershell
python -m unittest tests.test_windows_foundation_service_probe tests.test_windows_foundation_service_serialization -v
```

O teste nativo exige o motor inbox Windows PowerShell 5.1 Desktop, compara a quantidade e os nomes do inventário real com a consulta direta, verifica os quatro campos e uma consulta individual, e regista os dois tempos. Não fixa a quantidade de serviços nem exige que estados mutáveis permaneçam iguais entre leituras. O teste de serialização exige zero acessos às propriedades relacionadas.

Ambos os módulos já entram no runner Windows pelo prefixo `test_windows_foundation_`. O teste de descoberta garante a inclusão da aceitação 5.1, e o gate recusa skips nativos em Windows. Futuras alterações da sonda devem conservar esta aceitação nativa.
