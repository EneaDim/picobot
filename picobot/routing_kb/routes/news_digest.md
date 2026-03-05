# news_digest

## Intent
Rassegna notizie / digest:
- cercare sul web via SearXNG (web_search)
- fetch pagine via sandbox_web (whitelist)
- summarizer con output 6–8 bullet + link
Opzionale: TTS/podcast.

## Strong signals
- prefisso: "/news ..." o "news: ..."
- parole: notizie, news, rassegna, digest, aggiornamenti, “cosa è successo”
- richieste “ultime notizie su X”

## Italiano: esempi
- /news intelligenza artificiale europa
- news: intelligenza artificiale europa
- fammi una rassegna stampa su energia e gas
- ultime notizie su openai e regolamentazione UE
- dammi un digest di 7 bullet con link su: elezioni, economia, inflazione
- cosa è successo oggi su bitcoin?
- notizie recenti su Apple in Europa

## English: examples
- /news AI regulation Europe
- news: AI regulation Europe
- give me a news digest with links about inflation
- latest news on OpenAI policy in the EU
- what happened today about bitcoin?

## Negative examples
- domande su documenti locali (kb_query)
- riassunto youtube
- tool python/file/web espliciti
