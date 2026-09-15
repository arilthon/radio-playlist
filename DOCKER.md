# Executar com Docker

A imagem inclui código e dependências Python. Credenciais, tokens, cadastros, bancos e backups não entram no contexto de construção. Os dados ficam no volume `radio-data`, montado em `/data`. O processo usa um usuário sem privilégios.

## Construir e iniciar

Configure o `.env` a partir do `.env.example` se ainda não tiver um. Pare o painel local antes de iniciar o contêiner, pois ambos usam a porta 8090.

```bash
docker compose up -d --build
```

Abra http://127.0.0.1:8090 . A imagem local se chama `radio-playlist:local`.

Para somente construir:

```bash
docker build -t radio-playlist:local .
```

As portas 8090 (painel), 8080 (TIDAL) e 8081 (Spotify) são publicadas apenas em `127.0.0.1` do computador. O servidor escuta em `0.0.0.0` dentro do contêiner para permitir o encaminhamento. O painel não tem autenticação de usuário e não deve ser publicado na internet.

## Primeiro login

No aplicativo de desenvolvedor, mantenha o endereço de retorno configurado:

- TIDAL: `http://localhost:8080/callback`
- Spotify: `http://127.0.0.1:8081/callback`

Cadastre/selecione a rádio no painel e use seu ID no comando abaixo (a rádio principal usa `default`). Pare essa rádio pelo painel antes de executar:

```bash
docker compose exec radio python radio.py --profile default --dry-run --once
```

Para outra rádio, substitua `default` pelo ID exibido no comando de primeiro login do painel. Abra o link mostrado no navegador do computador que está executando o Docker e autorize em até três minutos. O contêiner não abre um navegador próprio. As portas de callback já estão encaminhadas. O token fica no volume para os próximos acessos. Depois inicie a rádio pelo painel no modo desejado.

## Trazer os dados da instalação local (opcional)

Faça esta migração antes de começar a usar a instalação Docker. Pare todos os monitores e o painel locais para copiar os bancos sem gravações concorrentes. Partindo de um contêiner novo e parado:

```bash
docker compose create --build
for arquivo in history.sqlite3 radios.json .tidal-cache.json .spotify-cache.json stations; do
  if [ -e "$arquivo" ]; then
    docker compose cp "$arquivo" radio:/data/
  fi
done
docker compose run --rm --no-deps --user root radio chown -R radio:radio /data
docker compose up -d
```

Isso transfere cadastros, fila, histórico, escolhas e tokens existentes. Não execute a cópia sobre uma instalação Docker já em uso: ela substituiria arquivos do volume. O `.env` continua no host e é injetado pelo Compose, sem ser incorporado à imagem.

## Operação

```bash
docker compose ps
docker compose logs --tail=100 radio
docker compose stop
docker compose down
```

`down` preserva o volume. Não use `down -v` se deseja conservar os dados. Ao encerrar o contêiner, o painel para seus monitores. Ao reiniciar, as rádios iniciadas pelo painel nesta versão retomam automaticamente no último modo. O botão Parar e o arquivamento desabilitam a retomada da rádio. Monitores iniciados diretamente no terminal não são cadastrados para retomada. Se faltar autorização, a retomada mostra o motivo no diagnóstico e requer corrigir o login e iniciar a rádio. O healthcheck confirma apenas que o painel responde, não que as rádios ou serviços musicais estão conectados.

Para aplicar mudanças no `.env`:

```bash
docker compose up -d --force-recreate
```

## Docker Desktop com WSL

Se o comando informar que Docker não está disponível nesta distribuição WSL, abra Docker Desktop → Settings → Resources → WSL Integration, habilite a distribuição e aplique. Depois confira `docker version` no terminal WSL e execute o comando de construção.

## Versões automáticas no GitHub (GHCR)

O workflow `.github/workflows/docker.yml` executa os testes e constrói a imagem em pushes para `main` e pull requests. Ao enviar uma tag no formato `v1.2.3`, publica também `ghcr.io/arilthon/radio-playlist:1.2.3` para Linux AMD64. Se os testes falharem, a publicação não acontece. As Actions estão fixadas por commit.

A autenticação usa o `GITHUB_TOKEN` fornecido pelo GitHub com permissão `packages: write`. Não é necessário cadastrar as credenciais do TIDAL ou Spotify nos secrets do GitHub. O `.dockerignore` limita o conteúdo da imagem ao código e dependências.

Depois de enviar o código para `main`, publique uma versão inédita:

```bash
git tag -a v1.0.0 -m 'Versão 1.0.0'
git push origin v1.0.0
```

Acompanhe a execução na aba **Actions** do repositório; a imagem aparecerá em **Packages**. Não reutilize tags já publicadas. A automação publica somente a versão exata, sem atualizar `latest`, evitando que uma publicação antiga altere a versão padrão.

Para usar uma imagem publicada, adicione ao `.env`:

```dotenv
RADIO_IMAGE=ghcr.io/arilthon/radio-playlist:1.0.0
```

Então execute:

```bash
docker compose pull radio
docker compose up -d --no-build radio
```

A imagem só estará disponível depois que o workflow terminar com sucesso. O GHCR pode criar o pacote como privado: para baixar, autentique o Docker com uma conta com acesso ao pacote e um token com `read:packages`, ou altere a visibilidade em **Package settings** se quiser distribuí-lo publicamente. Não coloque o token no repositório.

Para atualizar, troque `RADIO_IMAGE` pela nova versão e repita os comandos. Para voltar, escolha uma versão anterior. Faça backup dos dados antes de atualizar; mudanças de estrutura no banco podem exigir restauração do backup. O volume existente é preservado ao recriar o serviço. A publicação no GitHub não atualiza automaticamente o aplicativo no seu computador.

Referência: https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images


## Continuidade da captura e recuperação da fila

Falhas de autorização ou acesso à playlist pausam as inclusões, mantendo a captura ativa e a fila persistente. O acesso é verificado novamente a cada 60 segundos; respostas 429 respeitam a espera do serviço e a coordenação compartilhada entre rádios.

Falhas individuais temporárias recebem até cinco tentativas, com esperas de 60, 120, 240 e 480 segundos. Durante a espera, outras músicas podem ser processadas. Faixas inválidas e tentativas esgotadas aparecem na revisão manual; corrigir e reprocessar reinicia as tentativas. Erros de playlist ou de renovação do token não consomem tentativas individuais. As músicas já tocadas enquanto o aplicativo estava completamente desligado não podem ser recuperadas pelo stream ICY.

Na primeira atualização para esta versão, inicie as rádios pelo painel para registrar a preferência de retomada. Faça backup do volume antes de atualizar: o banco recebe automaticamente colunas para controlar as tentativas.
