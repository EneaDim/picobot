# chat

## Intent
Conversazione generale, domande aperte, brainstorming, spiegazioni, riscrittura, traduzioni (senza bisogno di tool),
help generico, richieste non riconducibili chiaramente a KB/news/youtube/tools.

## Italiano: esempi
- ciao come va?
- spiegami cos’è un agent locale
- fammi un esempio di prompt
- riscrivi questo testo in modo più chiaro: ...
- traduci in inglese: ...
- dammi idee per un progetto python
- aiutami a scegliere tra due opzioni
- cos’è ollama e come lo uso?

## English: examples
- hi, what can you do?
- explain local-first agents
- rewrite this paragraph: ...
- translate to italian: ...
- give me ideas for a python project
- compare option A vs option B

## Negative examples (should not be chat)
- /news ... (news digest)
- news: ... (news digest)
- youtube link (youtube summarizer)
- pdf/document/kb question (kb_query)
- tool sandbox_python {...} (tool)
