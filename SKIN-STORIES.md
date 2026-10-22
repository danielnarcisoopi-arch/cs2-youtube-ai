# CS2 Skin Stories — versão sem ligação à OpenAI

## Instalar esta atualização

Copia os ficheiros do ZIP para a raiz do repositório, mantendo as pastas e substituindo os ficheiros existentes. Inclui a pasta `.github/workflows`. O nome do workflow passa a ser **CS2 Skin Stories**.

Esta versão substitui a anterior: não usa chave OpenAI, modelo GPT nem qualquer serviço de geração de texto. Não precisas de configurar pagamento OpenAI. Podes apagar o secret `OPENAI_API_KEY` se só o criaste para este workflow; não é lido por esta série.

## Como cria conteúdo diferente

O gerador local combina sete formatos com escolha de skins, armas, limites de orçamento e comentários calculados a partir dos dados:

1. Budget: três skins de uma arma sob um limite verificado.
2. Duel: duas skins da mesma arma e diferença exata de preço.
3. Loadout: rifle T, rifle CT e pistola, com total acumulado e orçamento verificado.
4. Wear: duas categorias da mesma finish e diferença de preço. A arte de catálogo não comprova o float de um item individual.
5. Premium vs. budget: duas skins da mesma arma em faixas de preço diferentes.
6. Supply picks: skins com ofertas disponíveis; não confunde ofertas com vendas.
7. Watchlist: três opções económicas para comparar, sem previsões de lucro.

Há seis aberturas locais por formato, escolha contra os hooks recentes e perguntas finais variadas. O formato menos usado recentemente tem prioridade. Uma finish fica excluída dos próximos **12 vídeos**, mesmo que tenha outro wear. A combinação exata de formato, skins, orçamento e moeda não volta a ser usada enquanto o histórico for conservado. Se alguém forçar muitas vezes o mesmo formato, as aberturas são reutilizadas pela ordem menos recente quando as seis se esgotarem.

O texto é programático e factual; não é um guião livre escrito por IA. A variedade vem de formatos, skins e dados diferentes. Não inventa características visuais, não promete valorização, não simula crafts de stickers e não afirma semelhanças com skins caras sem verificação.

## Publicação e primeiro teste

- Três execuções agendadas por dia: **10:00, 15:00 e 19:00 UTC**. Em Portugal continental, os mesmos horários no inverno e uma hora mais tarde no verão.
- Os horários somam-se aos outros workflows. O GitHub pode atrasar execuções.
- O agendamento funciona quando o ficheiro está na branch predefinida e Actions está ativo.
- Continua a usar o secret `YOUTUBE_TOKEN_JSON` dos workflows existentes.
- Em Settings → Actions → General → Workflow permissions, permite **Read and write permissions** para guardar o histórico.
- Não apagues a branch `cs2-skin-stories-history`: contém a memória de temas e skins. A atualização preserva o histórico anterior.

Em **Actions → CS2 Skin Stories → Run workflow**, escolhe `format = auto` e mantém **upload desmarcado** no primeiro teste. O artifact `cs2-skin-story-…` contém o vídeo MP4 e o JSON de evidências. Para uma publicação manual, marca upload. As execuções agendadas publicam automaticamente quando todos os passos têm sucesso.

## Imagem, voz e dados

Cada cena mostra a arte exata da skin escolhida, com movimento de zoom/pan, nome, wear, preço e texto sincronizado com a narração. Usa arte de catálogo em movimento, não uma gravação do jogo ou um inspect 3D. Os preços são lowest asks em USD da Skinport, com stock, não preços Steam nem vendas concluídas. As imagens ilustram a skin; inspeciona o float e pattern do item real antes de comprar.

A voz mantém o sistema existente: ElevenLabs opcional, Edge neural e Piper como alternativa local. O guião não depende de nenhum desses serviços; servem apenas para sintetizar a voz. As ligações à Skinport, catálogo/imagens, GitHub e YouTube continuam necessárias.

Não publica sem imagens exatas, preços válidos ou um tema novo. Não usa preço sugerido quando falta uma oferta real. Previews concluídos também entram no histórico. Uma falha ambígua de upload não faz retry automático de um vídeo inteiro; confirma o YouTube Studio antes de upload manual.

## Validação desta versão

- **15 testes offline passaram**, incluindo simulação de 21 vídeos consecutivos, rotação dos sete formatos, proteção por finish, cálculos de orçamento e diferenças de preço, aberturas sem repetição enquanto há variantes disponíveis e persistência de histórico.
- O fluxo de publicação foi exercitado sem qualquer chave de IA, com os serviços externos simulados. Isto não é uma publicação real.
- Compilação Python validada e montagem de MP4 vertical testada com arte sintética e áudio de teste.
- Skinport, imagens, serviços de voz e publicação real não foram validados ponta a ponta neste ambiente. O primeiro preview manual no GitHub continua necessário. Nenhum vídeo foi publicado nesta sessão.

Testes:

```bash
python -m unittest discover -s tests -p 'test_editorial.py' -v
```

Para gerar só o plano e o guião local:

```bash
UPLOAD_ENABLED=false python -m cs2_shorts.editorial --plan-only
```
