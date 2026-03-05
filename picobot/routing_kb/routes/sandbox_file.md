# sandbox_file

## Intent
Operazioni file sandboxate: preview/lettura/lista directory, path locali entro root consentita.

## IT
- apri il file README.md
- mostrami il contenuto di ./docs/notes.txt
- lista la directory ./docs
- che file ci sono in questa cartella?

## EN
- open file README.md
- show me ./docs/notes.txt
- list directory ./docs

## Explicit tool
- tool sandbox_file {"root":".","path":"README.md"}

## Negative
- kb_query (quando l’utente vuole risposta basata su index)
