# Rádio → playlists TIDAL e Spotify

Python 3.10+. Captura metadados ICY da rádio, compara músicas no TIDAL ou Spotify e adiciona a faixa aprovada à playlist indicada. Cada cadastro de rádio usa um serviço; os cadastros existentes permanecem no TIDAL.


## Conectar o Spotify

1. Crie um aplicativo no [Spotify Developer Dashboard](https://developer.spotify.com/dashboard). Em Development Mode, o proprietário do aplicativo precisa ter Spotify Premium, conforme os [requisitos oficiais](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide).
2. Cadastre a Redirect URI **`http://127.0.0.1:8081/callback`** exatamente. Spotify não aceita `localhost` para esse retorno.
3. Preencha `SPOTIFY_CLIENT_ID` no `.env`. Os campos `SPOTIFY_REDIRECT_URI` e `SPOTIFY_COUNTRY_CODE=BR` já têm valores padrão. O login usa OAuth PKCE e não precisa do Client Secret.
4. No painel, clique em **Adicionar rádio**, selecione **Spotify** e informe a URL da rádio e o link de uma playlist que sua conta possa editar. Para acompanhar a mesma emissora nos dois serviços, crie cadastros separados com nomes distintos.
5. Selecione a nova rádio e copie o comando de **Primeiro login no terminal** mostrado no painel:

```bash
.venv/bin/python radio.py --profile ID_DO_CADASTRO --dry-run --once
```

6. Autorize no navegador. Depois, no painel, escolha **Adicionar à playlist** e inicie essa rádio.

O Spotify possui cache de login `.spotify-cache.json` e pausa de requisições `.spotify-rate.json` próprios. O TIDAL continua usando seus arquivos atuais. Busca, duplicatas, fila, revisão manual, aprendizado, reprocessamento e diagnósticos funcionam com o serviço escolhido no cadastro. Os IDs das escolhas manuais não são transferidos entre serviços; cadastre uma rádio nova ao trocar de destino. Cadastros antigos sem campo `provider` continuam no TIDAL.

A busca Spotify traz até dez candidatos com artistas na mesma resposta. A playlist é lida por páginas usando `GET /playlists/{id}/items`; inclusões usam `POST /playlists/{id}/items`. Fontes: [PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow), [retorno OAuth](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri), [itens da playlist](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items), [inclusão](https://developer.spotify.com/documentation/web-api/reference/add-items-to-playlist).

A validação automática simula as APIs. O teste com uma conta Spotify real exige preencher o Client ID e concluir a autorização.

## Configuração

O ambiente `.venv` já está instalado neste workspace. Para instalar em outra máquina:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Preencha o `.env` local:

- `TIDAL_CLIENT_ID` e `TIDAL_CLIENT_SECRET`: crie um aplicativo no [painel TIDAL](https://developer.tidal.com/). A assinatura não substitui as credenciais do aplicativo.
- Configure no aplicativo a Redirect URI `http://localhost:8080/callback`, exatamente igual a `TIDAL_REDIRECT_URI`.
- Habilite os escopos `playlists.write` e `search.read` para o aplicativo, quando solicitado no painel.
- `PLAYLIST_ID`: UUID ou link de uma playlist TIDAL que sua conta possa editar. Exemplo de formato: `https://tidal.com/browse/playlist/550e8400-e29b-41d4-a716-446655440000`.
- `RADIO_STREAM_URL`: URL direta do áudio com metadados ICY, não a página do player. Para M3U/PLS, use a URL de áudio contida nele.
- `TIDAL_COUNTRY_CODE`: país do catálogo, padrão `BR`.
- `POLL_INTERVAL`: intervalo em segundos, padrão `30`.

## Executar

Somente leitura da rádio, sem login:

```bash
.venv/bin/python radio.py --radio-only --once
```

Buscar no TIDAL sem adicionar:

```bash
.venv/bin/python radio.py --dry-run --once
```

Monitorar e adicionar automaticamente:

```bash
.venv/bin/python radio.py
```

No primeiro acesso, o programa abre o navegador e também exibe o link de autorização. Entre na sua conta TIDAL e autorize o aplicativo. O retorno é recebido automaticamente em `http://localhost:8080/callback`; volte ao terminal para acompanhar. Se o navegador não abrir, abra o link exibido no navegador do mesmo computador. O programa aguarda até três minutos. Em WSL, o navegador do Windows precisa conseguir acessar a porta local do WSL. Em servidor remoto, encaminhe a porta 8080 para sua máquina antes do login. Não compartilhe a URL de retorno.

O token fica em `.tidal-cache.json`, com acesso restrito ao usuário, e é renovado automaticamente. Não compartilhe o cache nem o `.env`. Para trocar de conta ou refazer um login revogado, remova apenas `.tidal-cache.json` e execute novamente. Ctrl+C encerra o monitoramento; mantenha o terminal aberto para continuar.

## Comportamento

- Espera `Artista - Música`; outros formatos são ignorados. O filtro não reconhece todas as vinhetas.
- Compara até dez candidatos por artista e título, normalizando acentos e pontuação. Exige pontuação mínima de 0,88 e aceita versões ao vivo do mesmo artista e música. Prefere estúdio entre os candidatos aprovados quando a rádio não informa uma versão; se informa ao vivo, prioriza ao vivo. Continua rejeitando diferenças de remix, karaokê, instrumental e acústico. Resultados incertos ficam no histórico sem inclusão. É uma heurística, não uma garantia de identificação.
- Antes de incluir, consulta todas as páginas da playlist e o histórico persistente por playlist/ID TIDAL. Faixas registradas anteriormente não são reinseridas mesmo se removidas manualmente da playlist. IDs diferentes da mesma gravação ainda podem passar; execute apenas uma instância por playlist.
- No monitoramento normal, mantém uma conexão ICY contínua. A captura salva títulos em uma fila SQLite independente das chamadas TIDAL. O modo `--once` lê até cinco blocos. Timeout de 15 segundos por operação de rede.
- Falhas transitórias são tentadas novamente no próximo ciclo. Respostas 429 respeitam `Retry-After`. Falhas de acesso exigem corrigir credenciais, permissões ou playlist.
- Após falha de inclusão, a próxima tentativa consulta novamente a playlist. Alterações simultâneas por outro programa ou atraso de atualização da API ainda podem causar duplicatas.
- Sem reconhecimento de áudio. Rádios sem ICY precisam de integração específica; músicas curtas podem passar entre consultas.

## Validação

```bash
.venv/bin/python -m unittest -v
```

Testes simulam as APIs e o login. A integração real depende de suas credenciais e da URL da rádio.

Implementação baseada na [API pública TIDAL](https://tidal-music.github.io/tidal-api-reference/) e no [fluxo OAuth oficial com PKCE](https://developer.tidal.com/documentation/api-sdk/api-sdk-authorization). Usa `GET /v2/searchResults` e `POST /v2/playlists/{id}/relationships/items`.

## Histórico e versão anterior

A versão anterior foi salva em `backups/versao-tidal-original.tar.gz`, sem credenciais, tokens ou ambiente Python. Para restaurar o código, extraia em uma pasta separada e siga as instruções de instalação dessa versão.

O arquivo `history.sqlite3` registra data/hora UTC, título da rádio, playlist, estado, ID TIDAL e pontuação quando disponível. Estados: detectada, adicionada, duplicada, ignorada, nao_encontrada, incerta, simulacao e erro. Simulações não são marcadas como inclusões.

```bash
.venv/bin/python radio.py --history
```

Mostra os últimos 20 registros sem acessar o TIDAL. Guarde uma cópia do banco para preservar o histórico entre instalações. A verificação de duplicatas usa IDs, não compara gravações com IDs distintos. A busca consulta os artistas dos candidatos e a playlist antes de cada inclusão, aumentando o número de chamadas à API.

### Limite de requisições (429)

O programa espaça chamadas à API em pelo menos um segundo e reutiliza metadados por dez minutos (até 256 entradas em memória). A playlist é consultada novamente antes de incluir. Em 429, respeita `Retry-After` em segundos ou data HTTP, com espera progressiva mínima de 60 segundos até 15 minutos; um prazo maior informado pelo servidor prevalece. O modo `--once` informa a espera e encerra. Use uma única instância e reinicie o app para carregar atualizações de código. Durante a pausa do TIDAL, a captura continua salvando títulos na fila.

### Captura e fila persistente

O modo normal captura continuamente os títulos ICY e salva em `history.sqlite3` antes de processar. Erros transitórios e 429 mantêm a faixa pendente e não pausam a captura. Ao reiniciar, o programa retoma a fila da playlist configurada. A fila de `--dry-run` é separada da fila de inclusões reais. Execute somente uma instância por banco/playlist.

Entradas consecutivas iguais são ignoradas; títulos idênticos já pendentes são agrupados. O histórico registra `capturada` assim que recebe o título e `detectada` quando inicia o processamento. Resultados incertos ou não encontrados continuam no histórico para consulta, mas saem da fila automática. A captura não recupera títulos que a emissora não enviou, faixas anteriores à instalação desta mudança ou períodos sem conexão/sem o programa rodando. Falta de correspondência no catálogo ainda impede a inclusão.

## Painel visual e diagnóstico (Linux/WSL)

```bash
.venv/bin/python dashboard.py
```

Abra **http://127.0.0.1:8090** no navegador do mesmo computador. O painel mostra a última faixa capturada (não garante que ainda esteja tocando), fila, totais e últimos 50 eventos, com horários locais. Atualiza a cada três segundos. Os dados abrangem todas as playlists/modos registrados neste banco.

Escolha **Simular inclusões**, **Adicionar à playlist** ou **Apenas ouvir metadados** e clique em **Iniciar monitor**. O botão **Parar** controla apenas o processo iniciado pelo painel. Se já iniciou `radio.py` em outro terminal, pare com Ctrl+C naquele terminal antes de iniciar pelo painel. Uma trava impede monitores duplicados. Fechar a aba não encerra o monitor; Ctrl+C no servidor do painel encerra também o monitor iniciado por ele.

**Verificar conexão** testa configuração, rádio, token e leitura da playlist, sem adicionar músicas. Pare o monitor antes; existe um intervalo mínimo de um minuto entre testes. O diagnóstico de leitura não comprova permissão de escrita. Se precisar autorizar a conta, faça primeiro `.venv/bin/python radio.py --dry-run --once` no terminal e conclua o login pelo navegador. Credenciais continuam no `.env`; não são exibidas no painel. O arquivo local `.dashboard.log` recebe a saída do monitor e pode conter o link temporário de autorização; não compartilhe seu conteúdo integral.

O painel usa apenas a biblioteca padrão do Python e escuta no endereço local. Não o publique como servidor de internet.

## Várias rádios simultâneas

No painel, clique em **Adicionar rádio**, informe nome, URL direta do áudio e playlist TIDAL. O cadastro fica em `radios.json`. A **Rádio principal** continua usando o `.env` e o histórico existentes; novas rádios usam `stations/<id>/` para filas, histórico e logs próprios.

Selecione uma rádio na lista, escolha o modo e clique em **Iniciar monitor**. Alterne para outra rádio e inicie-a também. Cada botão **Parar** afeta apenas a rádio selecionada. Os indicadores da lista mostram quais estão ativas. Cadastrar uma rádio não a inicia automaticamente. Os dados são preservados ao reiniciar o painel, mas os processos precisam ser iniciados novamente.

As credenciais e o login TIDAL são compartilhados. O app coordena a renovação do token, o espaçamento das chamadas e a pausa por 429 entre os processos. Se várias rádios usarem a mesma playlist, a etapa de busca/verificação/inclusão é serializada para evitar inserções simultâneas; a captura de todas continua independente. Isso não elimina o limite do TIDAL: quanto mais rádios, maior pode ficar a fila.

Para executar pelo terminal, use o ID do cadastro em `radios.json`:

```bash
.venv/bin/python radio.py --profile ID_DA_RADIO
.venv/bin/python radio.py --profile ID_DA_RADIO --history
```

A rádio original continua disponível com `radio.py` sem parâmetros. Reinicie processos antigos após atualizar para que usem as novas travas compartilhadas. Esta versão permite cadastrar e controlar rádios; edição e remoção pelo painel ainda não estão disponíveis.

## Revisão manual, aprendizado e reprocessamento

Selecione a rádio e abra **Revisão manual**. A lista mostra até 100 títulos cujo último resultado foi incerto, não encontrado, ignorado ou com erro. Novas buscas guardam os candidatos (artista, título e versão); registros antigos podem estar sem candidatos. Nesse caso, use **Reprocessar com as regras atuais** para atualizar a busca, ou informe diretamente um link/ID de faixa TIDAL.

- **Escolher esta faixa** ou **Salvar escolha e enfileirar** grava a associação do título da rádio com o ID TIDAL e agenda uma tentativa. Não há inclusão direta pelo botão: o monitor processa a fila com verificação de duplicatas e limites da API.
- Selecione **Simulação** ou **Adicionar à playlist** na janela de revisão. Para executar a tentativa, deixe essa rádio ativa no mesmo modo; filas de simulação e inclusão são separadas. As solicitações usam a playlist registrada no evento original.
- A escolha é aprendida mesmo quando a tentativa é uma simulação. Ela será usada nas próximas ocorrências também no modo de inclusão. Diferenças de caixa e espaços são normalizadas; a associação é específica do título e da rádio. A faixa escolhida é validada por ID no TIDAL antes de usar.
- Em **Escolhas aprendidas**, use **Esquecer escolha** para voltar à busca automática. Isso não remove músicas da playlist nem desfaz uma inclusão em andamento. Uma escolha nova substitui a anterior.
- Cada linha do histórico possui **Reprocessar / escolher**, inclusive registros antigos. O pedido fica salvo em disco e não exige esperar a música tocar novamente. Repetir o pedido enquanto uma tentativa está em andamento preserva a nova solicitação para o próximo ciclo.

Os candidatos e as escolhas ficam no banco de cada rádio; não são compartilhados entre emissoras. Escores exibidos são medidas heurísticas, não probabilidades. Escolhas manuais não recebem escore automático. Se o ID informado não existir ou não puder ser acessado, o TIDAL poderá recusar a tentativa: corrija/esqueça a escolha no painel antes de reiniciar o monitor.

## Estado detalhado, avisos e indicadores por rádio

O painel separa **Captura** (conectando, lendo stream, reconectando, sem leitura recente ou parada) de **TIDAL / fila** (aguardando músicas, processando, pausa por 429, nova tentativa ou erro). Em esperas, mostra o tempo restante. A última faixa exibida vem da captura, não de um reprocessamento antigo.

As leituras do stream atualizam uma confirmação local aproximadamente a cada cinco segundos, inclusive quando não há título novo. Mais de 45 segundos sem confirmação gera um aviso de ausência de leitura recente; isso é um sinal de diagnóstico, não prova de desconexão ou música perdida. Processos antigos precisam ser reiniciados para enviar esses dados. Estados persistidos não são apresentados como ativos quando o monitor está parado.

Os indicadores contam eventos das **últimas 24 horas**, incluindo capturas, inclusões, duplicatas, resultados incertos, não encontrados, simulações, erros e entradas ignoradas. Repetições e reprocessamentos contam novamente; não são contagens de músicas únicas nem uma taxa de sucesso. A fila mostra quantas inclusões e simulações estão pendentes, com a data da pendência mais antiga que possui horário registrado. Pendências criadas antes desta atualização não recebem datas inventadas.

Avisos destacam falhas de rádio/TIDAL, login revogado, permissões, fila com monitor parado e pendências em um modo diferente do ativo. Cada rádio tem seus próprios estados e métricas; a lista superior mostra o processamento e o tamanho da fila de cada emissora, sem novas chamadas ao TIDAL.

## Arquivar e restaurar rádios

Selecione uma rádio adicionada e clique em **Arquivar rádio**. O painel encerra o monitor que ele próprio iniciou e oculta a rádio da lista principal. Histórico, fila, escolhas aprendidas e configuração são preservados. Nenhuma playlist ou música é removida do TIDAL/Spotify.

Marque **Mostrar rádios arquivadas**, selecione a emissora e clique em **Restaurar rádio** para voltar à lista principal. A restauração não inicia a captura: escolha o modo e inicie quando desejar. Rádios arquivadas não podem ser iniciadas pelo painel nem pelo comando `radio.py --profile`.

Se a rádio foi iniciada em outro terminal, pare-a nesse terminal antes de arquivar. A **Rádio principal**, configurada pelo `.env`, não pode ser arquivada nesta versão. O arquivamento é reversível e não exige confirmação adicional.

## Imagem Docker

```bash
docker compose up -d --build
```

Acesse http://127.0.0.1:8090 . Consulte [DOCKER.md](DOCKER.md) para login, persistência, migração dos dados locais e configuração do Docker Desktop/WSL. O `.env` é fornecido em tempo de execução e não entra na imagem.


### Editar uma rádio

Selecione a rádio e clique em **Editar rádio**. Pare o monitor e aguarde qualquer diagnóstico antes de salvar. Nome e URL podem ser alterados sem apagar histórico, fila ou escolhas. Serviço e playlist só podem ser trocados enquanto a rádio não tem dados; para mudar o destino de uma rádio já utilizada, cadastre outra.

A rádio principal também pode ser editada: suas configurações salvas no painel passam a prevalecer sobre nome, URL, playlist e serviço originais. As credenciais continuam no `.env`. No Docker, as edições ficam no volume persistente. Salvar não inicia o monitor.
