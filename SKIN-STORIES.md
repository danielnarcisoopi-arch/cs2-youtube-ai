# CS2 Skin Stories — instalação e teste

Este pacote acrescenta uma série independente aos Shorts de mercado, gameplay e táticas existentes.

## Instalar

Extrai o ZIP e copia os ficheiros para a raiz do repositório, mantendo as pastas, incluindo `.github/workflows`. Substitui apenas `src/cs2_shorts/media.py` e `src/cs2_shorts/scripts.py`; os restantes ficheiros são novos. Não é necessário substituir a base de dados nem carregar o projeto todo.

Em **Settings → Secrets and variables → Actions → Secrets**, acrescenta:

- `OPENAI_API_KEY`: chave da API OpenAI com faturação ativa. A subscrição ChatGPT não inclui estes consumos. O workflow usa imagens para escrever comentários visuais em inglês.
- `YOUTUBE_TOKEN_JSON`: o mesmo secret já usado pelos outros workflows.
- `ELEVENLABS_API_KEY`: opcional, para a voz premium já suportada.

Em **Variables**, podes configurar `ELEVENLABS_VOICE_ID` se usares ElevenLabs e `EDITORIAL_AI_MODEL` se quiseres mudar o modelo. O modelo tem de aceitar imagens, Responses API e Structured Outputs. Por omissão usa `gpt-4.1-mini`.

Em **Settings → Actions → General → Workflow permissions**, permite **Read and write permissions**. O histórico é guardado automaticamente na branch dedicada `cs2-skin-stories-history`, sem competir com as atualizações da base de dados dos outros workflows. Não apagues essa branch: conserva a memória dos temas.

## Primeiro teste

1. Abre **Actions → CS2 Skin Stories (AI) → Run workflow**.
2. Mantém `upload = false` e `format = auto`.
3. Abre o artifact `cs2-skin-story-…` da execução.
4. Vê o MP4 e o JSON com as skins exatas, preços, guião, fonte e horário da recolha.
5. Depois de veres o resultado, podes correr com `upload = true` para publicar outro vídeo.

As execuções agendadas publicam automaticamente. O agendamento entra em funcionamento quando este ficheiro está na branch predefinida e GitHub Actions está ativo.

## Frequência

Três tentativas de geração/publicação por dia: **10:00, 15:00 e 19:00 UTC**. Em Portugal continental, os mesmos horários no inverno e 11:00, 16:00 e 20:00 no verão. Estes vídeos somam-se aos restantes workflows. O GitHub pode atrasar execuções; estes horários não são uma garantia ao minuto.

Para alterar a frequência, edita o `cron` em `.github/workflows/cs2-skin-stories.yml`.

## Como varia o conteúdo

Sete formatos, alternando entre os que têm dados válidos:

- Budget: três skins de uma arma sob um limite verificado.
- Duel: duas skins da mesma arma para o público escolher.
- Loadout: rifle T, rifle CT e pistola, com soma dos preços verificada.
- Wear: duas categorias de wear da mesma skin; imagens de catálogo são ilustrativas.
- Premium versus budget: duas skins da mesma arma com preços bastante diferentes.
- Supply picks: três skins com várias ofertas disponíveis; não confunde ofertas com vendas.
- Watchlist: três skins abaixo de um orçamento, para comparar sem prever lucros.

O formato menos usado recentemente tem prioridade. Uma finish fica excluída dos próximos **12 vídeos**, mesmo que tenha outro wear. O histórico impede repetir a mesma combinação no mesmo formato e orçamento. O guião da IA vê as imagens escolhidas e os hooks anteriores. Os preços e os nomes são inseridos pelo código a partir da fonte, não inventados pela IA.

Cada vídeo tem hook, cenas individuais com arte exata, preço e wear, comentários narrados e pergunta final. Os cards recebem movimento de zoom/pan. A narração é sincronizada por cena e é também mostrada no vídeo. Esta série usa arte de catálogo em movimento; não representa uma gravação do jogo nem um inspect 3D. Não usa uma imagem de fundo genérica para todas as skins.

## Limites e comportamento em falha

- Preços em USD por omissão, Skinport, lowest ask com stock. Não representa preço Steam nem vendas concluídas.
- Não usa `suggested_price` quando não existe oferta real.
- Não publica sem imagens exatas, sem dados atuais ou se não encontrar um tema novo.
- A IA tem até três tentativas para produzir um guião que passe as regras. Não substitui silenciosamente o guião por um template.
- Uma narração que exigisse aceleração excessiva bloqueia o vídeo.
- ElevenLabs é opcional; usa Edge neural e depois Piper como alternativas. A qualidade da voz depende do serviço que estiver disponível.
- A proteção de conteúdo não é uma garantia de correção semântica de todos os comentários gerados; revê os primeiros previews.
- Não gera ainda montagens de stickers/crafts nem afirma semelhança com Dragon Lore. Esses formatos precisam de composição visual e verificação próprias. Não promete retorno financeiro nem confunde custo de stickers com valor de revenda.
- O histórico é reservado antes da tentativa de upload. Se a resposta do YouTube falhar depois de aceitar o vídeo, consulta o Studio antes de fazer upload manual; não há retry automático de um upload inteiro.
- Previews renderizados também entram no histórico para a próxima execução não produzir o mesmo conteúdo.
- Se a branch de histórico existir mas perder o ficheiro, o workflow falha em vez de apagar a memória.

## Validação feita nesta entrega

- 12 testes automatizados offline passaram, incluindo simulação de 21 vídeos consecutivos, alternância dos sete formatos, exclusão por finish, limites de orçamento, ausência de preços inválidos, alinhamento do guião e persistência do histórico.
- Compilação Python validada.
- Smoke test do renderer: MP4 H.264/AAC vertical 1080 × 1920, 13,07 segundos, com arte sintética e áudio silencioso exclusivamente de teste. Cards inspecionados visualmente. Esse ficheiro de teste não é um exemplo de conteúdo final e não está no pacote.
- **Não foi validada aqui uma execução real ponta a ponta**: acesso à Skinport e instalação de dependências foram bloqueados pelo ambiente. IA, imagens externas, síntese de voz e upload real precisam do primeiro teste manual no GitHub. Não foi publicado nenhum vídeo nesta sessão.

Testes no repositório:

```bash
python -m unittest discover -s tests -p 'test_editorial.py' -v
```

Para produzir só o plano e guião, sem renderizar nem publicar:

```bash
UPLOAD_ENABLED=false python -m cs2_shorts.editorial --plan-only
```

Sem chave de IA, podes inspecionar um plano local com `--plan-only --template-mode`. Este modo é explicitamente não-IA e não permite publicação.
