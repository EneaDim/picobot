# youtube_summarizer

## Intent
Riassumere contenuti YouTube:
- ottenere transcript/sottotitoli (yt-dlp)
- riassumere (summarizer agent)
- fallback su metadata se captions non disponibili

## Strong signals
- URL youtube.com / youtu.be
- parole: “youtube”, “video”, “riassumi il video”, “summary of this video”
- frasi “sporche” con URL in mezzo (molto comune)

## Italiano: esempi realistici
- riassumi questo video: https://www.youtube.com/watch?v=ssYt09bCgUY
- fammi il riassunto del video youtube https://youtu.be/ssYt09bCgUY
- puoi estrarre il transcript e riassumerlo?
- mi fai i punti chiave + takeaway?
- voglio una sintesi in italiano, bullet points
- trova i sottotitoli e poi fammi un summary

## English: examples
- summarize this video https://www.youtube.com/watch?v=ssYt09bCgUY
- get transcript and summarize it
- key takeaways from this YouTube video: https://youtu.be/ssYt09bCgUY
- summarize in bullet points

## Edge cases
- link con testo davanti: "summarize this youtube video: https://..."
- link con parentesi o punteggiatura: "(https://youtu.be/...)"
- url non valido/troncato: watch?v=abc (dovrebbe comunque tentare di estrarre url, poi fallback/errore gestito)

## Negative examples
- news digest (notizie/attualità)
- kb_query su documenti locali
