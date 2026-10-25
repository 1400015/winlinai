# Roadmap de Melhorias e Novas Funcionalidades — WinLinAI

**Data:** 23 de outubro de 2026
**Versão atual:** 1.4.2
**Análise baseada em:** Código-fonte (31.322 linhas em 109 módulos), documentação, testes (1684 passando), CI/CD

---

## 📊 Resumo Executivo

O WinLinAI é um assistente de IA maduro para Linux/Windows com:
- ✅ **Arquitetura sólida**: Separação GTK/Qt, providers modulares, storage atômico
- ✅ **Segurança robusta**: Encriptação de credenciais, validação de paths, isolamento de processos
- ✅ **Cobertura de testes boa**: 1684 testes passando, CI multi-plataforma
- ✅ **Documentação extensa**: 20+ documentos técnicos detalhados

**Áreas de oportunidade identificadas:** 15 novas funcionalidades, 12 melhorias de UX, 8 otimizações de infraestrutura

---

## 🎯 Prioridades

| Prioridade | Descrição | Prazo sugerido |
|------------|-----------|----------------|
| **P0 - Crítico** | Bugs, segurança, estabilidadade | Imediato (1-2 semanas) |
| **P1 - Alto** | Funcionalidades core, UX essencial | Curto prazo (1-2 meses) |
| **P2 - Médio** | Melhorias de experiência, nice-to-have | Médio prazo (3-6 meses) |
| **P3 - Baixo** | Polimento, экспериментальные | Longo prazo (6+ meses) |

---

## 🚀 NOVAS FUNCIONALIDADES

### P1 - Alto Impacto

#### 1. **Sistema de Plugins Aprimorado** ⭐⭐⭐
**Estado atual:** Existe estrutura básica em `plugins/` mas subutilizada

**Proposta:**
- Marketplace de plugins comunitários (repositório GitHub separado)
- Sandbox de plugins (execução isolada com permissões limitadas)
- UI de gerenciamento de plugins (instalar/desinstalar/ativar/desativar)
- Assinatura digital de plugins
- Categorias: Novos providers de IA, Novos temas, Integrações (Slack, Discord, etc.), Ferramentas de sistema

**Arquivos afetados:** `src/ai_client.py`, `plugins/`, nova `src/plugin_manager.py`

**Esforço estimado:** 2-3 semanas

---

#### 2. **Suporte a Modelos Locais Avançado (Ollama/LM Studio)** ⭐⭐⭐
**Estado atual:** Suporte básico a Ollama/OpenAI-compatible

**Proposta:**
- Download e gerenciamento de modelos locais (GGUF)
- Interface de seleção de modelo com detalhes (tamanho, quantização, licencia)
- Múltiplos servidores locais simultâneos
- Auto-start de servidor local
- Métricas de performance local (tokens/s, latência)
- Suporte a llama.cpp, vLLM, LocalAI

**Arquivos afetados:** `src/ai_providers/local_llm.py`, `src/remote_models.py`, nova `src/local_model_manager.py`

**Esforço estimado:** 3-4 semanas

---

#### 3. **Assistente de Voz (Speech-to-Text / Text-to-Speech)** ⭐⭐⭐
**Estado atual:** Não existe

**Proposta:**
- Integração com Whisper (local) ou APIs de STT (Google, Azure)
- TTS com espeak-ng, pico2wave ou APIs (ElevenLabs, Google)
- Modo "conversa por voz" hands-free
- Configuração de voz (idioma, velocidade, pitch)
- Atalho global para ativar/desativar microfone

**Arquivos afetados:** Nova `src/voice_assistant.py`, `src/main_window.py`, `src/qt_chat.py`

**Esforço estimado:** 2-3 semanas

---

#### 4. **Integração com Aplicações do Sistema** ⭐⭐
**Estado atual:** Captura de tela, OCR, clipboard básico

**Proposta:**
- **Clipboard inteligente:** Detectar código/URLs/erros no clipboard e oferecer ações
- **Seleção de texto global:** Atalho para capturar texto selecionado em qualquer app
- **Integração com browser:** Extensión para enviar páginas/seleções para o assistente
- **Integração com terminal:** Plugin para bash/zsh/fish (histórico, sugestões)
- **Integração com IDE:** Plugin VSCode/Cursor (explicar código, gerar testes, refatorar)

**Esforço estimado:** 4-6 semanas (por integração)

---

#### 5. **Sistema de Agendamento e Automação** ⭐⭐
**Estado atual:** Não existe

**Proposta:**
- Tarefas agendadas ("todos os dias às 9h, verifica atualizações")
- Triggers condicionais ("quando bateria < 20%, sugerir economia de energia")
- Workflows: sequências de ações baseadas em condições
- Notificações proativas baseadas em padrões de uso
- Integração com systemd timers (Linux) / Task Scheduler (Windows)

**Arquivos afetados:** Nova `src/scheduler.py`, `src/automation_engine.py`

**Esforço estimado:** 3-4 semanas

---

### P2 - Médio Impacto

#### 6. **Modo Colaborativo / Multi-usuário** ⭐⭐
- Compartilhamento de conversas (links temporários)
- Sessões colaborativas em tempo real
- Perfis de usuário separados
- Controle de acesso baseado em roles

**Esforço estimado:** 4-6 semanas

---

#### 7. **Base de Conhecimento Pessoal (RAG Avançado)** ⭐⭐
**Estado atual:** Busca lexical básica em documentos locais

**Proposta:**
- **Embeddings locais:** Usar sentence-transformers para busca semântica
- **Indexação vetorial:** ChromaDB, FAISS ou Qdrant local
- **Suporte a PDFs:** Extração de texto de PDFs (PyPDF2, pdfplumber)
- **Suporte a mais formatos:** DOCX, XLSX, PPTX, HTML, Markdown
- **Importação de pastas:** Indexação recursiva com monitoramento de alterações
- **Citações precisas:** Referências a documento/página/linha
- **Modo offline completo:** Tudo local, sem enviar dados para APIs

**Arquivos afetados:** `src/document_store.py`, nova `src/rag_engine.py`

**Esforço estimado:** 4-5 semanas

---

#### 8. **Integração com Serviços Cloud** ⭐⭐
- Sincronização de conversas entre dispositivos (E2E encriptado)
- Backup automático para cloud (Nextcloud, Dropbox, Google Drive)
- Importação de documentos de cloud storage
- Integração com calendários (Google Calendar, Outlook)
- Integração com email (Gmail, Outlook)

**Esforço estimado:** 3-4 semanas (por serviço)

---

#### 9. **Modo Presentation / Demonstração** ⭐
- Interface em tela cheia para apresentações
- Respostas com animações
- Modo "palco" com controle remoto (smartphone como controle)
- Gravação de sessões de demo

**Esforço estimado:** 2-3 semanas

---

#### 10. **Suporte a Multi-monitor Avançado** ⭐
**Estado atual:** Suporte básico a xrandr/Sway

**Proposta:**
- Perfis de monitor (casa, escritório, apresentação)
- Hot-plug de monitores com reconfiguração automática
- Suporte a fractional scaling
- Suporte a VRR (Variable Refresh Rate)
- Configuração de layouts (side-by-side, stacked, mirrored)
- Perfis por aplicação (forçar app em monitor específico)

**Arquivos afetados:** `src/display_actions.py`

**Esforço estimado:** 2-3 semanas

---

### P3 - Baixo Impacto / Experimentais

#### 11. **Modo Jogo / Gaming Assistant** ⭐
- Otimização de sistema para jogos (desativar compositor, prioridade de CPU)
- Overlay de performance (FPS, temperaturas, uso de GPU)
- Sugestões de launch options (Steam, Lutris)
- Gravação de gameplay (OBS integration)

---

#### 12. **Assistente de Codificação Avançado** ⭐
- **Code review automático:** Analisar diffs e sugerir melhorias
- **Geração de testes:** Gerar testes unitários para código existente
- **Documentação automática:** Gerar docstrings e README
- **Refatoração assistida:** Sugerir padrões de design
- **Terminal integrado:** Terminal embutido na interface

---

#### 13. **Suporte a Containers/VMs** ⭐
- Gerenciamento de Docker/Podman containers
- Criação de VMs (libvirt, VirtualBox)
- Snapshots e backup de containers
- Logs de containers na interface

---

#### 14. **Integração com Home Assistant / IoT** ⭐
- Controle de dispositivos smart home
- Automações baseadas em IA
- Dashboard de dispositivos
- Comandos de voz para IoT

---

#### 15. **Modo Offline Completo "Air-gapped"** ⭐
- Modo 100% offline (sem verificações de update, telemetria)
- Modelos locais apenas (sem chamadas a APIs)
- Base de conhecimento local expandida
- Documentação offline completa

---

## 🎨 MELHORIAS DE UX/UI

### P0 - Crítico

#### 1. **Corrigir Flaky Test GTK** 🔴
**Problema:** Segfault intermitente em `test_changing_preferences_controls_buttons_after_show_all`
**Impacto:** CI instável, confiança reduzida

**Solução:**
- Adicionar `@pytest.mark.flaky(reruns=3)` ou retry logic
- Isolar teste problemático
- Investigar race condition no GTK CSS

**Arquivo:** `tests/test_wayland_feature_fixes.py`

---

### P1 - Alto

#### 2. **Onboarding / Tutorial Interativo** ⭐⭐⭐
**Estado atual:** Sem tutorial para novos usuários

**Proposta:**
- Wizard de primeiro uso (5-7 passos)
- Tour guiado pelas funcionalidades principais
- Dicas contextuais (tooltips "did you know?")
- Progresso salvo (pode pular/retomar)
- Vídeos curtos embutidos (opcional)

**Arquivos afetados:** Nova `src/onboarding.py`, `src/main_window.py`

---

#### 3. **Temas Personalizados Avançados** ⭐⭐
**Estado atual:** 4 temas built-in + editor básico

**Proposta:**
- Editor visual de temas (WYSIWYG)
- Importar/exportar temas (JSON)
- Temas da comunidade (galeria online)
- Temas automáticos (baseados em wallpaper, hora do dia)
- Modo alto contraste para acessibilidade
- Preview em tempo real

---

#### 4. **Atalhos de Teclado Personalizáveis** ⭐⭐
**Estado atual:** Atalhos fixos (Ctrl+S, Ctrl+E, etc.)

**Proposta:**
- UI para reconfigurar todos os atalhos
- Perfis de atalhos (vim, emacs, default)
- Atalhos contextuais (diferentes na janela de chat vs configurações)
- Visualizador de atalhos em uso (conflitos)

---

#### 5. **Busca Global na Interface** ⭐⭐
- Busca unificada: conversas, configurações, documentos, guias
- Resultados em tempo real (fuzzy search)
- Atalho global (Ctrl+Space ou similar)
- Histórico de buscas

---

#### 6. **Modo Foco / Focus Mode** ⭐
- Interface minimalista (apenas chat)
- Ocultar todos os controles
- Atalho para toggle (F11 ou similar)
- Ideal para apresentações ou concentração

---

### P2 - Médio

#### 7. **Notificações Inteligentes** ⭐⭐
- Agrupamento de notificações similares
- Modo "não incomodar" com exceções
- Notificações ricas (ações inline: "Responder", "Lembrar depois")
- Resumo diário/semanal de uso

---

#### 8. **Dashboard de Estatísticas Avançado** ⭐⭐
**Estado atual:** Estatísticas básicas de tokens

**Proposta:**
- Gráficos interativos (uso ao longo do tempo)
- Comparação entre providers/modelos
- Custos estimados por período
- Exportar relatórios (PDF, CSV)
- Metas de uso (orçamento mensal)

---

#### 9. **Modo Compacto / Mini** ⭐
- Janela redimensionável para tamanho mínimo
- Modo "sempre no topo" flutuante pequeno
- Apenas input + última resposta
- Ideal para consultas rápidas

---

#### 10. **Suporte a Emojis e Reações** ⭐
- Reações a mensagens (👍 👎 ❤️ etc.)
- Sugestões de emoji baseadas no contexto
- Emoji picker integrado

---

#### 11. **Arrastar e Soltar Melhorado** ⭐
- Arrastar arquivos diretamente para a janela
- Arrastar imagens da web
- Arrastar texto de outras aplicações
- Preview antes de anexar

---

#### 12. **Modo Escuro Automático** ⭐
- Seguir tema do sistema operacional
- Transição suave (amanhecer/anoitecer)
- Agendamento personalizado

---

## 🔧 MELHORIAS TÉCNICAS

### P1 - Alto

#### 1. **Otimização de Performance** ⭐⭐⭐
**Áreas identificadas:**

| Módulo | linhas | Oportunidade |
|--------|--------|-------------|
| `main_window.py` | 1670 | Dividir em sub-módulos (já iniciado: `main_window_capture.py`, `main_window_dialogs.py`) |
| `ai_client.py` | 1391 | Extrair retry logic, separar transports |
| `config_manager.py` | 1400 | Cache de configurações, lazy loading |
| `cli.py` | 1425 | Dividir por comandos (chat, sessions, config, etc.) |
| `offline_assistant.py` | 1313 | Cache de respostas, índice de intenções |

**Ações específicas:**
- Lazy loading de providers (carregar apenas quando necessário)
- Cache de modelos remotos (TTL configurável)
- Compressão de histórico antigo (gzip)
- Índices para busca em documentos (SQLite FTS5)

---

#### 2. **Migração para Type Hints Completo** ⭐⭐
**Estado atual:** Type checking gradual (alguns módulos)

**Proposta:**
- 100% type hints em novos módulos
- `mypy --strict` para módulos core
- Pyright como alternativa/complemento
- Documentação de tipos (docstrings com tipos)

---

#### 3. **Logging Estruturado** ⭐⭐
**Estado atual:** Logging básico

**Proposta:**
- JSON logging para análise
- Níveis de log por módulo configuráveis
- Rotação de logs com retenção configurável
- Envio de logs para sistemas externos (opcional: Sentry, Loki)
- Correlation IDs para rastreamento de requisições

---

#### 4. **Configuração via Arquivo + UI + CLI + Env** ⭐
- Todas as configurações acessíveis por:
  - Arquivo JSON (atual)
  - UI de configurações (atual)
  - CLI (`winlinai config set key value`)
  - Variáveis de ambiente (parcial)
  - API REST local (nova)

---

### P2 - Médio

#### 5. **Suporte a Wayland Nativo Completo** ⭐⭐
**Estado atual:** Suporte via layer-shell, portals

**Proposta:**
- Protocolo nativo Wayland para janela flutuante
- Suporte a wlroots compositors (Sway, Hyprland, river)
- Otimizações específicas por compositor

---

#### 6. **Empacotamento Universal** ⭐⭐
**Estado atual:** deb (APT), xbps (Void), Flatpak, MSI (Windows)

**Proposta:**
- AppImage (portabilidade máxima)
- Snap package
- AUR (Arch User Repository)
- Nix package
- Homebrew (macOS - futuro)
- Winget (Windows Store)

---

#### 7. **API REST Local** ⭐⭐
- Servidor HTTP local (127.0.0.1:port)
- Endpoints para:
  - Enviar mensagens (`POST /chat`)
  - Gerenciar conversas (`GET/POST/DELETE /sessions`)
  - Buscar documentos (`GET /documents/search`)
  - Configurações (`GET/PUT /config`)
- Autenticação via token local
- WebSocket para streaming de respostas
- Documentação OpenAPI/Swagger

**Uso:** Integração com outras apps, scripts, web UI

---

#### 8. **Telemetria Opcional (Privacy-first)** ⭐
- Métricas de uso anônimas (opt-in)
- Crash reporting (Sentry, opt-in)
- Feature usage analytics
- A/B testing framework
- Tudo com opção de desativar completamente

---

## 🌍 INTERNACIONALIZAÇÃO

### P1 - Alto

#### 1. **Suporte a Mais Idiomas** ⭐⭐
**Estado atual:** en, pt, es, fr, de (parcial)

**Idiomas prioritários para adicionar:**
- 🇮🇹 Italiano
- 🇷🇺 Russo
- 🇨🇳 Chinês (zh-CN, zh-TW)
- 🇯🇵 Japonês
- 🇰🇷 Coreano
- 🇮🇳 Hindi
- 🇹🇷 Turco
- 🇵🇱 Polaco
- 🇳🇱 Holandês
- 🇸🇪 Sueco

**Processo:**
- Extrair todas as strings para arquivo de template (`.pot`)
- Usar Weblate ou similar para tradução colaborativa
- Revisão por falantes nativos
- Testes de UI para texto longo (overflow)

---

#### 2. **Localização de Conteúdo (L10n)** ⭐
- Guias offline traduzidos (atualmente PT/EN)
- Modelos de IA com instruções no idioma local
- Data/hora/número formatados por locale
- Unidades de medida (métrico/imperial)

---

## 🔒 SEGURANÇA E PRIVACIDADE

### P1 - Alto

#### 1. **Auditoria de Segurança Contínua** ⭐⭐
- SAST (Semgrep, Bandit) no CI
- Dependency scanning (Dependabot, Snyk)
- Secret scanning (gitleaks, trufflehog)
- Container scanning (Trivy)
- Penetration testing periódico

---

#### 2. **Modo Privado / Private Mode** ⭐
- Sessões que não são salvas em disco
- Histórico apenas em memória
- Limpar memória ao fechar (secure delete)
- Indicador visual de modo privado

---

#### 3. **Assinatura de Código** ⭐
**Estado atual:** Sem assinatura

**Proposta:**
- Assinar releases (GPG para Linux, Authenticode para Windows)
- Verificar assinatura no auto-update
- Publicar chaves públicas
- Documentar verificação manual

---

## 📦 INFRAESTRUTURA E DEVOPS

### P1 - Alto

#### 1. **CI/CD Otimizado** ⭐⭐
**Melhorias:**
- Cache de dependências (pip, apt)
- Testes paralelos (pytest-xdist)
- Build de artifacts apenas quando necessário
- Release automático em tags (semantic-release)
- Changelog automático (conventional commits)
- Docker images para testes (reprodutibilidade)

---

#### 2. **Monitoramento de Qualidade** ⭐⭐
- Code coverage > 80% (atual: ~78% core, 70% GTK)
- SonarQube ou CodeClimate
- Benchmark de performance (pytest-benchmark)
- Testes de carga (locust)

---

#### 3. **Documentação Viva** ⭐⭐
- Documentação gerada automaticamente (Sphinx/MkDocs)
- API docs (OpenAPI/Swagger)
- Tutoriais interativos (Jupyter notebooks)
- Video tutoriais (YouTube embed)
- FAQ baseado em issues do GitHub

---

### P2 - Médio

#### 4. **Ferramentas de Desenvolvimento** ⭐
- Pre-commit hooks (ruff, mypy, black)
- Dev containers (VSCode)
- Makefile/Taskfile para comandos comuns
- Script de setup de ambiente de dev
- Docker compose para dependências de teste

---

#### 5. **Distribuição Contínua** ⭐
- Nightly builds (últimas mudanças do master)
- Canary releases (beta testers)
- Feature flags para rollout gradual
- Rollback automático em caso de crash rate alto

---

## 📋 ROADMAP VISUAL

### Q4 2026 (Out-Dez)
```
Semana 1-2:  [P0] Corrigir flaky test GTK
              [P1] Otimização de performance (lazy loading)

Semana 3-4:  [P1] Sistema de plugins aprimorado
              [P1] Onboarding/tutorial interativo

Semana 5-6:  [P1] Suporte a mais idiomas (it, ru, zh)
              [P1] API REST local (v1)

Semana 7-8:  [P1] RAG avançado (embeddings locais)
              [P2] Dashboard de estatísticas

Semana 9-10: [P1] Assistente de voz (STT/TTS)
              [P2] Notificações inteligentes

Semana 11-12: [P1] Modelos locais avançado (Ollama)
               [P2] Temas da comunidade
```

### Q1 2027 (Jan-Mar)
```
- [P1] Integração com aplicações (clipboard, seleção de texto)
- [P1] Agendamento e automação
- [P2] Modo colaborativo
- [P2] Sincronização cloud (E2E)
- [P2] AppImage, Snap, AUR
- [P3] Modo jogo
```

### Q2 2027 (Abr-Jun)
```
- [P2] Suporte a containers/VMs
- [P2] Home Assistant/IoT
- [P3] Assistente de codificação avançado
- [P3] Modo presentation
- [P3] Modo air-gapped completo
- [P2] macOS support (investigação)
```

---

## 🎯 MÉTRICAS DE SUCESSO

| Métrica | Atual | Meta Q1 2027 | Meta Q2 2027 |
|---------|-------|--------------|--------------|
| Testes passando | 1684 | 2000+ | 2500+ |
| Cobertura de código | ~78% | 85% | 90% |
| Idiomas suportados | 5 | 10 | 15 |
| Providers de IA | 7 | 10 | 12 |
| Downloads mensais | ? | +50% | +100% |
| Stars no GitHub | ? | +30% | +60% |
| Contribuidores ativos | ? | 10+ | 20+ |
| Tempo médio de resposta | ? | -20% | -40% |

---

## 📝 PRÓXIMOS PASSOS IMEDIATOS

1. **Esta semana:**
   - [ ] Corrigir flaky test GTK (P0)
   - [ ] Criar issues no GitHub para cada item P1
   - [ ] Definir owners para cada feature

2. **Este mês:**
   - [ ] Implementar sistema de plugins aprimorado
   - [ ] Adicionar 3 novos idiomas (it, ru, zh)
   - [ ] Criar API REST local v1

3. **Este trimestre:**
   - [ ] RAG avançado com embeddings
   - [ ] Assistente de voz
   - [ ] Onboarding interativo

---

## 🤝 COMO CONTRIBUIR

1. Escolha um item deste roadmap
2. Abra uma issue de discussão no GitHub
3. Proponha design/implementação
4. Submeta PR
5. Acompanhe reviews e CI

**Documentação para contribuidores:** `CONTRIBUTING.md` (a criar)

---

*Este roadmap é um documento vivo. Atualizações mensais baseadas em feedback da comunidade e prioridades do projeto.*
