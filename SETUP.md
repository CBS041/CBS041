# README profissional dinâmico — CBS041

Este pacote foi preparado para o repositório de perfil `CBS041/CBS041`.
Identidade: Inter, `#0A0A0A`, `#EDEDED` e azul `#036CB4`.

## Resultado

- Hero com posicionamento profissional, disponibilidade para estágio e **retrato ASCII**.
- Retrato obtido da **foto pública atual do GitHub** em cada atualização. Você pode sobrescrever usando `assets/portrait.png` (preferência permanente), mas **não é necessário** enviar outra foto.
- 3 cartões de contato (portfólio, LinkedIn e GitHub), cada um clicável no README.
- **Primeiros 4 repositórios fixados**: a API GraphQL retorna a ordenação real de `pinnedItems`. O workflow atualiza nomes, URLs, linguagens principais e descrições automaticamente. O gerador limita as descrições visualmente a 2 linhas, sem alterar a descrição original do GitHub.
- Contribuições reais dos últimos 365 dias, streak, dias ativos, melhor dia e heatmap na cor da marca.
- SVGs auto-contidos, sem JavaScript e sem CSS externo, com CSS keyframes/SMIL, WOFF subsetada embutida e versões estáticas selecionadas por `<picture media="(prefers-reduced-motion: reduce)">`.

## Primeira publicação

1. Copie o conteúdo deste pacote para a **raiz do repositório `CBS041/CBS041`**, numa branch de revisão. Os arquivos do README anterior serão substituídos quando a branch for mesclada.
2. No GitHub, habilite em **Settings → Actions → General** que o `GITHUB_TOKEN` tenha permissão de escrita do conteúdo do repositório; o workflow declara `permissions: contents: write`.
3. Execute **Actions → Atualizar perfil e repositorios fixados → Run workflow**. Aguarde o commit automático. Os dados iniciais em `data/profile.json` são intencionalmente vazios para não inventar atividade ou fixados; a primeira execução os substituirá por dados reais.
4. O workflow é executado diariamente, e o `README.md` é **regerado** ao mudar a ordem, nome, URL, linguagem ou descrição dos fixados. Faça personalizações de conteúdo no gerador, não diretamente no README autogerado.

**Token:** tente primeiro o token `github.token` padrão. Se a consulta GraphQL for recusada para dados da conta, crie o segredo `PROFILE_TOKEN` com acesso mínimo necessário. Para contribuições privadas, um token clássico `read:user` pode ser necessário; não exponha tokens no README ou nos SVGs. O workflow **não divulga o conteúdo de repositórios privados**: filtra a propriedade `isPrivate`.

## Executar localmente

```bash
python -m pip install -r requirements.txt
# Linux Ubuntu/Debian:
sudo apt-get install fonts-inter fonts-dejavu-core fontconfig
python -m unittest discover -s tests -v
python scripts/render_profile.py
STATIC=1 python scripts/render_profile.py
```

Para buscar dados novos, execute com `GITHUB_TOKEN` configurado:

```bash
GITHUB_TOKEN=seu_token python scripts/render_profile.py --refresh
```

`STATIC=1` substitui apenas as versões em `cards/` pelas versões do quadro final. Execute sem `STATIC=1` antes de publicar para recuperar as animações.

### Preview com dados de demonstração

```bash
python scripts/render_profile.py --data data/demo.json --out demo-cards
```

Os valores de contribuições no arquivo `data/demo.json` são **fictícios**; a seleção de repositórios nesse arquivo também é meramente ilustrativa, **não uma confirmação dos seus fixados atuais**. O gerador não usa esses dados para atualizar o README real. `demo-cards/` está no `.gitignore`.

## Restrições técnicas

- Imagens SVG não fazem requisições a GraphQL ao serem exibidas no README; o **GitHub Actions pré-renderiza** os valores diariamente.
- Links não funcionam de forma confiável **dentro** de `<img>`; por isso cada cartão é envolvido por um link `<a>` no `README.md`.
- Preferências de movimento reduzido podem não ser propagadas para SVGs aninhados no GitHub. O elemento `<picture>` força a versão estática como alternativa.
- Animações podem variar conforme navegador, app e cache do GitHub.
- Os cartões de demonstração usam dados fictícios; **não publique a prévia como estatística real**.
