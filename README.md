# Caçador de estágios de TI — RJ

Busca vagas de estágio de TI no Rio de Janeiro (e remotas), dá uma nota de aderência ao seu
perfil, organiza tudo no Trello e preenche os formulários de candidatura para você revisar e enviar.

**Fontes:** Gupy (que hospeda o site de carreira de muitas empresas), vagas.com, InfoJobs, Jobzi
(que agrega CIEE, Catho, Solides, BNE, Recrutei etc.) e Indeed.

## O dia a dia

```
 buscar.py (todo dia às 8h, sozinho)        você, no Trello                 aplicar.py
 ───────────────────────────────────        ───────────────                 ──────────
 vagas novas → coluna "Encontradas"  ──►  arrasta as que quer    ──►  abre cada vaga, preenche,
                                          para "Vou aplicar"           você revisa e clica Enviar
                                                                       → cartão vai p/ "Aplicada"
```

1. **De manhã**, abra o Trello. As vagas novas estão em *Encontradas*, com a nota no título.
   Abra o cartão para ver o motivo da nota e o link.
2. **Arraste para "Vou aplicar"** as vagas que interessam. Arquive as outras ou mande para *Descartada*.
3. **Rode `python aplicar.py`.** Para cada vaga da fila:
   - o Edge do assistente abre na vaga e clica em "Candidatar-se" quando encontra o botão;
   - se você não estiver logado no site, ele avisa (🔑): entre ali mesmo na janela (o "Entrar
     com Google" funciona) e aperte Enter. Ele volta para a vaga sozinho e continua;
   - em vagas.com, Catho, Empregos.com.br, InfoJobs e CIEE ele **não** clica no botão (✋): lá o
     "Candidatar-se" já envia na hora com o currículo cadastrado no site, então quem clica é você;
   - ele preenche nome, e-mail, telefone, LinkedIn, faculdade, currículo (PDF) e as perguntas abertas;
   - no terminal aparece o que foi preenchido e o que ficou faltando;
   - em formulários de várias etapas, ele clica em "Avançar"/"Próximo"/"Continuar" sozinho. Ele
     para quando falta um campo obrigatório, quando escreveu uma resposta aberta (para você
     revisar) e sempre que aparece um botão de envio ("Enviar", "Finalizar", "Concluir"...).
     Para desligar o avanço automático: `"avancar_etapas_sozinho": false` no `config.json`;
   - **perguntas do recrutador** ("Qual sua última remuneração?", "Tem disponibilidade...?"): ele
     preenche o que já sabe (suas respostas anteriores, seus dados, `respostas.md`) e para para
     você conferir. As que ficarem em branco, responda no site e aperte Enter: ele **guarda a sua
     resposta** em `respostas_aprendidas.md` e, na próxima vaga com pergunta parecida, já preenche;
   - **você confere e clica em Enviar no site.** O assistente nunca clica em botão de envio;
   - no terminal, digite `s` (enviei), `d` (descartar), `p` (pular) ou só **Enter** para ele
     continuar de onde parou.
4. Quando chamarem para entrevista, mova o cartão para *Entrevista*. Esta coluna é só sua.

## Primeira vez (uma vez só)

```bash
pip install -r requirements.txt
python aplicar.py --login
```

O `--login` abre o **Edge do assistente** (separado do seu Edge normal) com Gupy, vagas.com,
InfoJobs, Indeed, Solides, Catho, Empregos.com.br e CIEE (o Jobzi não tem login: as vagas dele
levam para esses sites). É um Edge comum, então "Entrar com Google" funciona. Entre nos sites
que você usa, **volte ao terminal e aperte Enter** (não feche o Edge antes). Ele mostra em quais
abas você ficou logado (✓) e em quais não (✗), guarda os logins e fecha o Edge.

Os logins ficam no perfil `dados/navegador` e numa cópia em `dados/sessao.json`. Os sites
expiram o login de tempos em tempos (a Solides, por exemplo); quando isso acontecer, o
`aplicar.py` avisa e você entra de novo na própria janela, sem precisar parar nada.

Só pode haver **um** Edge do assistente aberto por vez: se você rodar o `aplicar.py` com outro
ainda aberto (num terminal antigo), ele avisa para fechar.
Na Gupy, vale completar o perfil, porque é ele que vai para as empresas.

Depois, dê dois cliques em **`agendar_busca.bat`** para a busca rodar todo dia às 08:00. O Indeed
fica de fora da busca automática porque abre uma janela; para incluí-lo, rode `python buscar.py`
manualmente de vez em quando.

## Arquivos que você edita

| Arquivo | O que é |
|---|---|
| `dados_pessoais.json` | Dados que vão nos formulários. Campo vazio = o assistente não mexe. |
| `respostas.md` | Respostas padrão para perguntas abertas. **Revise, é a sua voz.** |
| `respostas_aprendidas.md` | Respostas que você deu nos formulários (o assistente cria e atualiza sozinho). Fica fora do GitHub. |
| `perfil.md` | Resumo do seu currículo, usado para dar notas e escrever respostas. |
| `config.json` | Termos de busca, cidades, nota mínima para ir ao Trello etc. |
| `.env` | Chaves do Trello e do Claude. Nunca compartilhe. |

## O que o assistente NÃO faz (de propósito)

- Não clica em Enviar, Finalizar, Concluir nem "Candidatura rápida"/"1 clique".
- Não clica em "Candidatar-se" nos sites em que esse botão já envia (vagas.com, Catho,
  Empregos.com.br, InfoJobs, CIEE).
- Não marca aceite de termos ou LGPD.
- Não preenche senha, CPF, "nome da mãe", "estado civil" nem a confirmação de e-mail.
- Não resolve CAPTCHA nem testes da Gupy (lógica, perfil comportamental). Esses são com você.

## Com ou sem a chave do Claude (`ANTHROPIC_API_KEY` no `.env`)

- **Sem a chave:** a nota é por palavras-chave, e as perguntas abertas usam os textos de
  `respostas.md`. Pergunta que não casa com nenhum texto fica em branco para você responder.
- **Com a chave:** o Claude lê cada vaga, dá uma nota explicada e escreve respostas sob medida
  para cada pergunta, usando só fatos do seu perfil.

## Comandos

```bash
python buscar.py                       # busca em todas as fontes e manda as boas para o Trello
python buscar.py --sem-trello          # teste: só gera a planilha em dados/
python buscar.py --fontes gupy jobzi   # só algumas fontes
python aplicar.py                      # processa a coluna "Vou aplicar"
python aplicar.py --login              # fazer login nos sites (mostra em quais entrou)
python aplicar.py --url LINK           # testar uma vaga avulsa, sem mexer no Trello
```
