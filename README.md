# Win-Cleaner

Programma portable per Windows che fa spazio sul disco con l'aiuto di un modello AI locale.
L'interfaccia è in italiano e ha lo stile di Windows 11.

1. **Mappa** il disco scelto (tutto, anche le cartelle di sistema, in circa un minuto).
2. **Classifica** con [Rizzo Flow](https://github.com/Rizzo-AI-Academy/rizzo-flow) le cartelle e i file
   più pesanti: cache, registri, installer, file di sviluppo rigenerabili, backup, documenti, foto,
   giochi, programmi, dati delle app. Il modello (Spark-X2.5-4B) gira sulla scheda video, nessun dato
   esce dal PC.
3. **Propone** cosa eliminare con spunte prudenti, che puoi cambiare come vuoi. Vedi il peso di ogni
   categoria (anello, barra e mappa del disco) e apri qualsiasi percorso in Esplora file con un clic.
4. **Elimina** solo dopo un riepilogo e una seconda conferma: nel Cestino di default, oppure in modo
   definitivo scrivendo ELIMINA.

Funziona anche su chiavette, dischi esterni e telefoni Android collegati via USB in modalità
"Trasferimento file" (dove non c'è un Cestino l'eliminazione è solo definitiva). Il supporto ai
telefoni è sperimentale.

Le cartelle di Windows, i programmi installati e le cartelle personali (Desktop, Documenti,
Download…) non si possono eliminare in blocco, qualunque cosa dica il modello. Le probabilità del
modello non sono calibrate: da sole non bastano mai a selezionare un'intera cartella.

## Uso

Copia la cartella `dist\Cleaner` dove vuoi e avvia `Cleaner.exe`. Istruzioni per l'utente in
`LEGGIMI.txt`. Per un'analisi completa avvialo come amministratore.

Requisiti: Windows 10 o 11 a 64 bit con WebView2. Consigliata una scheda NVIDIA con almeno 6 GB di
memoria; con altre schede usa Vulkan, senza scheda video il processore. Se il modello non si carica,
il programma funziona con le sole regole integrate.

## Sviluppo

Serve [uv](https://docs.astral.sh/uv/). Il modello e i runtime llama.cpp si scaricano con Rizzo Flow,
alla stessa versione usata dal progetto, in una cartella `rizzo-flow` accanto a questa:

```bash
git clone https://github.com/Rizzo-AI-Academy/rizzo-flow ../rizzo-flow
git -C ../rizzo-flow checkout d34665b7a28c62b79f37939f2fd83f5fe659fbf9
cd ../rizzo-flow && uv sync --locked && uv run rizzo download && uv run rizzo download --only runtime --runtime vulkan && cd -

uv sync
.venv/Scripts/python -m cleaner      # avvia l'app (modello e runtime da ../rizzo-flow)
.venv/Scripts/python -m pytest -q    # test
powershell -File build.ps1           # crea dist\Cleaner (circa 5 GB con il modello)
```

Dettagli tecnici in `CLAUDE.md`.

## Licenza

Win-Cleaner è distribuito con licenza [Apache-2.0](LICENSE). Crediti e componenti di terze parti in
[NOTICE](NOTICE).

## Crediti e licenze di terze parti

- [Rizzo Flow](https://github.com/Rizzo-AI-Academy/rizzo-flow), di Simone Rizzo — Rizzo AI Academy,
  Apache-2.0: il motore di classificazione. Win-Cleaner è un progetto indipendente, non affiliato.
- Pesi Spark-X2.5 di XHToken, Apache-2.0; [llama.cpp](https://github.com/ggml-org/llama.cpp), MIT.
- La cartella portable creata da `build.ps1` include i file di licenza e NOTICE di Rizzo Flow in
  `ai\`. Le librerie CUDA che contiene sono di NVIDIA e restano sotto la licenza NVIDIA.
