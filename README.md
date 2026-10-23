# PULSO

Portal estático de tecnologia com coleta incremental das 33 fontes aprovadas.

- Coleta: GitHub Actions, a cada três horas (`17 */3 * * *`, UTC) e execução manual em **Actions → Atualizar PULSO → Run workflow**. O agendamento do GitHub pode sofrer atrasos.
- Fontes: `sources.json`. As sete fontes recusadas permanecem explicitamente excluídas. Falhas de acesso ficam em `data/status.json` e na página Fontes; nenhuma falha apaga o histórico.
- Dados: `data/articles.json`, preservado em commits na `main`. A deduplicação usa a URL sem parâmetros de rastreamento. A descrição vem do feed da fonte; não há resumo nem tradução por IA.
- Início: 60 notícias mais recentes. Arquivo: todas as notícias, com filtros por assunto, fonte e mês. As páginas `arquivo-2.html` etc. oferecem acesso sem JavaScript; com JavaScript o filtro pesquisa o histórico inteiro.
- Salvas: armazenadas no navegador, acessíveis mesmo depois de a notícia sair da homepage. Não são sincronizadas entre dispositivos.
- Publicação: workflow oficial do GitHub Pages a partir da `main`; os HTMLs gerados também ficam na raiz do repositório.

## Manutenção

Edite `templates/`, `assets/` e `sources.json`. As páginas HTML da raiz são geradas automaticamente.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/collect.py
python3 scripts/build.py
node --check assets/app.js
```

Não são necessárias chaves de API, dependências Python externas nem serviços pagos. Uma fonte aprovada pode bloquear acesso automatizado ou mudar de formato; nesse caso a coleta é tentada novamente no próximo ciclo.

O GitHub pode desativar agendamentos de repositórios públicos após 60 dias sem atividade. Nesse caso, reative o workflow na aba Actions.
