# Caçador de estágios de TI — RJ

Busca vagas de estágio de TI no Rio de Janeiro (e remotas), dá uma nota de aderência ao seu
perfil, organiza tudo no Trello e preenche os formulários de candidatura para você revisar e enviar.

**Fontes:** Gupy (que hospeda o site de carreira de muitas empresas), LinkedIn (busca pública na região do Rio,
filtrada por nível estágio), Solides, vagas.com, InfoJobs, Jobzi (que agrega CIEE, Catho, BNE,
Recrutei etc.) e Indeed.

## O dia a dia

```
 buscar.py (todo dia às 8h, sozinho)        você, no Trello                 aplicar.py
 ───────────────────────────────────        ───────────────                 ──────────
 vagas novas → coluna "Encontradas"  ──►  arrasta as que quer    ──►  fase 1: prepara TODAS sozinho
                                          para "Vou aplicar"           fase 2: você confere e clica
                                                                       Enviar em cada uma
                                                                       → cartão vai p/ "Aplicada"
```

1. **De manhã**, abra o Trello. As vagas novas estão em *Encontradas*, com a nota no título.
   Abra o cartão para ver o motivo da nota e o link.
2. **Arraste para "Vou aplicar"** as vagas que interessam. Arquive as outras ou mande para *Descartada*.
3. **Rode `python aplicar.py`.** Ele trabalha em duas fases:

   **Fase 1, sem você** (pode deixar rodando e sair): abre **todas** as vagas de "Vou aplicar",
   cada uma numa aba, e leva cada uma até onde dá sozinho:
   - clica em "Candidatar-se", preenche nome, e-mail, telefone, LinkedIn, faculdade, currículo (PDF);
   - avança as etapas ("Avançar", "Próximo", "Salvar e continuar"...);
   - responde as perguntas do recrutador de **qualquer formato**: texto, Sim/Não, múltipla
     escolha, "marque as que se aplicam" e listas suspensas ("Escolha uma opção"). Usa, nesta ordem:
     o que você já respondeu antes (`respostas_aprendidas.md`), seus dados (`dados_pessoais.json`)
     e os seus textos (`respostas.md`). Resposta que vem dessas fontes entra **sem parar**;
   - deixa como está o que o site já marcou (ex.: "Você trabalha na empresa?": Não), e guarda na
     memória;
   - faixas numéricas: com `"cr": "7.6"` no `dados_pessoais.json`, a pergunta "Qual o seu CR?"
     com opções "Entre 7 e 8", "Entre 8 e 9"... é respondida sozinha;
   - perguntas de "Autorizo / Não autorizo o uso dos meus dados": responde **Autorizo**, porque
     `"autorizar_uso_de_dados": true` está no `config.json`. Mude para `false` se preferir responder você;
   - para em cada vaga quando precisa de você, e marca o cartão no Trello:
     - 🟩 **🤖 pronta p/ enviar**: chegou no botão final ("Enviar", "Finalizar"...); só falta você conferir e clicar;
     - 🟧 **🤖 precisa de você**: pergunta em branco, login, campo obrigatório, botão que ele não conhece;
     - 🟨 **🤖 envio direto no site**: vagas.com, Catho, Empregos.com.br, InfoJobs e CIEE, onde o
       "Candidatar-se" já envia na hora com o currículo cadastrado lá. Nesses ele não clica.

     O cartão ganha também um comentário dizendo o que falta.

   **Fase 2, com você**: mostra um resumo e traz cada aba para a frente, as prontas primeiro. Uma
   caixinha no canto da página e o terminal dizem o que ele espera de você:
   - 🔑 **login**: entre ali mesmo (o "Entrar com Google" funciona) e aperte Enter. Ele volta para
     a vaga e continua. Se você já entrou naquele site em outra aba, ele percebe sozinho;
   - ❓ **perguntas em branco**: responda no site (escreva, marque ou escolha) e aperte Enter. Ele
     **guarda a sua resposta** em `respostas_aprendidas.md` e, na próxima vaga com pergunta
     parecida, já responde sozinho. Se você corrigir algo que ele marcou, ele guarda a correção;
   - ✋ **pronta**: na última tela ele avisa o que falta, por exemplo "marque você 'Declaro que as
     informações são verdadeiras' e clique em 'Finalizar candidatura'". Na Gupy ele também lista os
     testes que vêm depois (ex.: "Teste de Perfil, Teste de Tecnologia"), que são com você, e anota
     no cartão do Trello quando você digita `s`;
   - ✋ **pronta**: confira e **clique você em Enviar**. O assistente nunca clica em botão de envio;
   - no terminal: `s` (enviei → cartão vai para *Aplicada*), `d` (descartar), `p` (pular: o
     cartão fica em "Vou aplicar" com a etiqueta), `q` (sair) ou **Enter** para ele continuar.

   Para desligar o avanço automático de etapas: `"avancar_etapas_sozinho": false` no `config.json`.
4. Quando chamarem para entrevista, mova o cartão para *Entrevista*. Esta coluna é só sua.

## Primeira vez (uma vez só)

```bash
pip install -r requirements.txt
python aplicar.py --login
```

O `--login` abre o **Edge do assistente** (separado do seu Edge normal) com Gupy, vagas.com,
InfoJobs, Indeed, Solides, Catho, Empregos.com.br, CIEE e LinkedIn (o Jobzi não tem login: as vagas dele
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
- Não marca caixinhas de aceite ("Declaro...", "Li e aceito os termos"): ele avisa, você marca.
  (A pergunta "Autorizo / Não autorizo o uso de dados" ele responde, por causa da sua regra no config.)
- Não roda duas vezes ao mesmo tempo: se já tiver um `aplicar.py` aberto em outro terminal, ele avisa.
- Não faz os testes da Gupy (perfil, lógica, inglês, fit cultural...): eles avaliam **você**.
  Ele só te avisa quais são.
- Não clica em "Candidatar-se" nos sites em que esse botão já envia (vagas.com, Catho,
  Empregos.com.br, InfoJobs, CIEE).
- Não preenche senha, CPF, "nome da mãe", "estado civil" nem a confirmação de e-mail.
- Não resolve CAPTCHA.

## Com ou sem a chave do Claude (`ANTHROPIC_API_KEY` no `.env`)

- **Sem a chave:** a nota é por palavras-chave, e as perguntas abertas usam os textos de
  `respostas.md`. Pergunta que não casa com nenhum texto fica em branco para você responder.
  Como a nota sai:
  - título de TI ("Estágio em Tecnologia", "Data Analytics", "Desenvolvimento"): começa em **6**,
    então vai para o Trello;
  - TI misturada com outra área ou foco (suporte, administrativo, operações): começa em **4**;
  - título sem TI: no máximo **5**; título de outra área (controladoria, finanças...): no máximo **3**;
  - cada skill sua que aparece na vaga soma **+1**, até 10.

  As listas ficam no `config.json` (`palavras_ti_titulo`, `areas_fora_ti`, `ti_periferica`,
  `minhas_skills`), e você pode editar.
- **Com a chave:** o Claude lê cada vaga, dá uma nota explicada e escreve respostas sob medida
  para cada pergunta, usando só fatos do seu perfil.

## Comandos

```bash
python buscar.py                       # busca em todas as fontes e manda as boas para o Trello
python buscar.py --sem-trello          # teste: só gera a planilha em dados/
python buscar.py --fontes gupy jobzi   # só algumas fontes
python buscar.py --reavaliar           # dá nota de novo em tudo (ex.: depois de mudar o config)
python aplicar.py                      # processa a coluna "Vou aplicar"
python aplicar.py --login              # fazer login nos sites (mostra em quais entrou)
python aplicar.py --url LINK           # testar uma vaga avulsa, sem mexer no Trello
```
