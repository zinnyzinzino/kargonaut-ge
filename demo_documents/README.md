# Simulated Georgian demo documents (paperwork agent)

Made by `generate_demo_documents.py` (do not edit by hand: change the script and run it with `--force`).
Every company, person, ID and phone number is invented, every page says SIMULATED, and our carrier is
Kargonaut Logistics LLC. Company names are English (as Georgian companies usually write them);
people's names are Georgian. Unlike `documents/` (real, private), these may be
committed, deployed and sent to Gemini.

Each folder is one load; `expected.json` is its answer key in the paperwork/schema.py format, generated from
the same data as the documents, with `must_flag` / `must_note` / `must_not_flag` / `must_not_invent`.

| Load | Documents | Scenario |
|---|---|---|
| `ge-01` | rc.pdf | Clean RC: everything stated and our company is the carrier. The happy path: read it, no problems, turn it into a draft load the dispatcher confirms. |
| `ge-02` | rc.pdf, bol.pdf | RC + BOL that agree, but write the same places differently (ქ. / ქუჩა, №, a first name added, a warehouse number) and write our company's name differently on the BOL (KARGONAUT LOGISTICS). No false alarm allowed. |
| `ge-03` | rc.pdf | The RC names another carrier (Lomi Trans Group). Problem: ask the broker for a revised RC. Not signed by us yet (we don't sign an RC with the wrong carrier). |
| `ge-04` | rc.pdf, bol.png | RC + BOL (a phone photo, PNG): the delivery address really differs (another street in Batumi). Problem: ask the broker whether the paperwork is acceptable for billing. The pickup address is the same, written differently. |
| `ge-05` | rc.pdf | The RC leaves the weight blank. Note 'not stated': the agent must not invent a weight, and the draft load must ask for it. |
| `ge-06` | rc.pdf, pod.pdf | A delivered load: RC + POD. The receiver signed with a scribble and left the print-name line empty. Problem: ask the driver to get the receiver's printed name. |
