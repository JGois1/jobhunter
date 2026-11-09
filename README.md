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
   - o navegador abre na vaga e clica em "Candidatar-se" quando encontra o botão;
   - ele preenche nome, e-mail, telefone, LinkedIn, faculdade, currículo (PDF) e as perguntas abertas;
   - no terminal aparece o que foi preenchido e o que ficou faltando;
   - **você revisa e clica em Enviar no site.** O assistente nunca envia sozinho;
   - no terminal, digite `s` (enviei), `d` (descartar), `p` (pular) ou só **Enter** para preencher
     de novo depois de avançar para a próxima etapa do formulário.
4. Quando chamarem para entrevista, mova o cartão para *Entrevista*. Esta coluna é só sua.

## Primeira vez (uma vez só)

```bash
pip install -r requirements.txt
python aplicar.py --login
```

O `--login` abre um navegador **separado do seu Edge normal** com Gupy, vagas.com, InfoJobs,
Indeed, Solides, Catho, Empregos.com.br e CIEE (o Jobzi não tem login: as vagas dele levam
para esses sites). É um Edge comum (sem automação), então "Entrar com Google" funciona. Entre nos sites
que quiser, **volte ao terminal e aperte Enter** (não feche o Edge antes: é no Enter que os
logins são copiados). Eles ficam em `dados/sessao.json` e no perfil `dados/navegador`.
Se você entrar em algum site durante o `aplicar.py`, esse login também é guardado.
Se algum site pedir login de novo no futuro, é só repetir o `--login`.
Na Gupy, vale completar o perfil, porque é ele que vai para as empresas.

Depois, dê dois cliques em **`agendar_busca.bat`** para a busca rodar todo dia às 08:00. O Indeed
fica de fora da busca automática porque abre uma janela; para incluí-lo, rode `python buscar.py`
manualmente de vez em quando.

## Arquivos que você edita

| Arquivo | O que é |
|---|---|
| `dados_pessoais.json` | Dados que vão nos formulários. Campo vazio = o assistente não mexe. |
| `respostas.md` | Respostas padrão para perguntas abertas. **Revise, é a sua voz.** |
| `perfil.md` | Resumo do seu currículo, usado para dar notas e escrever respostas. |
| `config.json` | Termos de busca, cidades, nota mínima para ir ao Trello etc. |
| `.env` | Chaves do Trello e do Claude. Nunca compartilhe. |

## O que o assistente NÃO faz (de propósito)

- Não clica em Enviar ou Finalizar.
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
python aplicar.py --login              # fazer login nos sites
```
