# Werkelijk uitgevoerd bewijs en vrijgavestatus

Datum: 18 oktober 2026. Basis:
`1647ed54299ae8c4343a5edf40b892307f7e6459` (gecontroleerde upstream exfat-next).
Uitgebreide herkomst, compiler, platform, dependencies, bron- en binaryhashes:
[environment.json](evidence/environment.json),
[build.json](evidence/build.json),
[sanitizer-build.json](evidence/sanitizer-build.json).

**Vrijgavestatus: experimentele Linux-imagefunctionaliteit; geen vrijgave voor
rechtstreeks gebruik op gebruikersvolumes.** De onderstaande groene proeven
heffen de beperkingen van ADR 0004 niet op. De normale build bouwt/installeert
de defragmenter niet.

| Uitgevoerde proef | Uitkomst | Bewijs |
| --- | --- | --- |
| Negen historische gerichte regressies | Alle negen vertonen op de vastgepinde baseline het verwachte defect; alle negen slagen op de herstelde worker | [baseline](evidence/baseline.json), [hersteld](evidence/regressions.json), [sanitizers](evidence/sanitizer-regressions.json) |
| Native model | 1.000 seeds × 5.000 iteraties, plus twee extra capacitycases; 1.002 geldige, daadwerkelijk gefragmenteerde invoerimages; alles eindigt met nul discontinuïteiten | [run](evidence/model.json), [caserecords](evidence/model-cases.jsonl) |
| ASan + UBSan + leak detection model | Dezelfde 1.002 cases, dezelfde afzonderlijk gecontroleerde uitkomsten, geen sanitizerdiagnostiek | [run](evidence/sanitizer-model.json), [caserecords](evidence/sanitizer-model-cases.jsonl) |
| Geometrie/vendor/bezetting/diepte-matrix | 288 native en 288 sanitizercases: 12 geometrieën × vier vendorvarianten × drie bezettingen × twee directorydieptes | [native](evidence/matrix.json), [sanitizers](evidence/sanitizer-matrix.json) |
| Linux-exFAT-driver | Tien seeds × 5.000 iteraties, offline defrag, remount en modelvergelijking; 130.242 expliciete workload-OS-calls, 44.629 effectieve modelmutaties en 1.280 extra fragmentatieacties | [driver](evidence/driver.json) |
| Kleine-fixture-foutmatrix | 651 cases; 646 werkelijk geraakte injecties. Alle 67 workerwriteposities met SIGINT/SIGTERM/SIGKILL/EIO, plus host-, retry-, flush-, persistent EIO/ENOSPC-, opnieuw onderbroken herstel- en onbetrouwbare-journalproeven | [native](evidence/faults.json), [sanitizers](evidence/sanitizer-faults.json), [posities](evidence/faults-cases.jsonl) |
| Expliciet persistencemodel | 154 native én 154 sanitizer-replays: prefixes, verlies, herordening en halve writes; steeds exact originele bytes na herstel | [native](evidence/persistence.json), [sanitizers](evidence/sanitizer-persistence.json) |
| Kopieer/publicatieproeven | 68 native én 68 sanitizercases: bron ongewijzigd, geen ongeldige output, echt link-EEXIST bij concurrente creator, zichtbare geldige output na post-link flushfouten | [native](evidence/publication.json), [sanitizers](evidence/sanitizer-publication.json) |
| Negatieve preflight | 29 native én 29 sanitizercases: cycles/crosslinks, bitmap, bad-clusterregistratie, onbekende allocatie/vendor, corruptie, overflowwaarden, ongeldige containers, lockconflict en links; volledige bronhash gelijk | [native](evidence/negative.json), [sanitizers](evidence/sanitizer-negative.json) |
| Metadata en bootbytes | 512- en 4096-byte sectoren; acht attribuutcombinaties, timestamps/subseconden/UTC, VDL en bootbytes buiten rootveld behouden | [native](evidence/metadata.json), [sanitizers](evidence/sanitizer-metadata.json) |
| Directoryflush en hostdeath | Workerflushfout doorgegeven; byte-exact undo. FIFO-journal geweigerd zonder blokkeren of writes. Hostkill terwijl worker na een write gestopt is: worker sterft en lock komt vrij vóór herstel | [native](evidence/transactions.json), [sanitizers](evidence/sanitizer-transactions.json) |
| Bestaande upstream-corruptiefixtures | 24 native en 24 sanitizercases, inclusief bestaande grote sparse fixture; detecteren, repareren, schoon herlezen | [native](evidence/upstream.json), [sanitizers](evidence/sanitizer-upstream.json) |
| Gewone autotools-build en make check | Beide bestaande interne suites slagen, nul skips | [log](evidence/autotools.log) |
| Schone patchtoepassing | Vijf commits zonder three-way-merge toegepast op de basis; identieke tree; schone build/smoke en upstreamsuite slagen | [controle](evidence/clean-apply.json) |
| Korte smoke-orchestrator | Build, baseline, herstel, negatieve cases en drie modelseeds werkelijk uitgevoerd | [smoke](evidence/smoke.json) |

De 1.000 hoofdseeds hebben 5.000.000 workloaditeraties. De twee extra capacitycases
brengen het run-totaal op 5.010.000 iteraties en 4.490.423 effectieve modelmutaties.
Native en sanitizer zijn aparte uitvoeringen van dezelfde seeds; ze worden niet
als 2.000 verschillende seeds opgeteld. De matrix staat eveneens apart en wordt
niet toegevoegd aan de claim van 1.000 random seeds. Een baseline-PASS betekent
dat het oude defect is aangetoond, niet dat de oude implementatie correct is.

## Werkelijk gebruikte commando's

De onderdelen zijn in aparte outputmappen uitgevoerd, zodat builds en proeven
onafhankelijk inspecteerbaar bleven. De exacte extra-suite-argv's staan in
[additional.json](evidence/additional.json) en
[sanitizer-additional.json](evidence/sanitizer-additional.json). De hoofdcommando's:

```sh
python3 tests/defrag/build.py --out build-defrag-tests-final --baseline
python3 tests/defrag/parallel.py --build build-defrag-tests-final \
  --cases 1000 --operations 5000 --jobs 4 \
  --out build-defrag-tests-final/qualification-model
python3 tests/defrag/build.py --sanitize --out build-defrag-tests-sanitize-final
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
python3 tests/defrag/parallel.py --build build-defrag-tests-sanitize-final \
  --cases 1000 --operations 5000 --jobs 4 \
  --out build-defrag-tests-sanitize-final/qualification-model
sudo -n python3 tests/defrag/mounted.py --build build-defrag-tests-final \
  --seeds 10 --operations 5000 --out build-defrag-tests-final/qualification-driver
python3 tests/defrag/qualify.py --out build-defrag-tests-final/qualification-smoke-final-proof
```

Foutinjectie onder ASan zet `DEFRAG_ASAN_RUNTIME` op
`cc -print-file-name=libasan.so`, zodat de ASan-runtime vóór de expliciete
workerinterposer wordt geladen. Python en fsck krijgen die interposer niet.

De volledige `qualify.py --full --driver` is beschikbaar als één reproduceerbaar
commando voor alle onderdelen; de huidige uitgebreide bewijsset is met de
bovenstaande afzonderlijke onderdelen uitgevoerd. De korte orchestratortest is
wel als geheel uitgevoerd. Dit onderscheid voorkomt een claim over een
full-orchestratorinvocatie die niet is gedaan.

## Waarschuwingen en niet-uitgevoerde claims

De expliciete builds geven drie bestaande waarschuwingstypen in ongewijzigde
code: ongebruikte `ui`-parameter zonder blkid en signednessvergelijkingen in
`lib/exfat_dir.c` en `fsck/fsck.c`. De historische baseline heeft bovendien
signed-char bitmapwaarschuwingen; de herstelde worker gebruikt unsigned char.
Er zijn geen nieuwe C-workercompilerwaarschuwingen.

Checkpatch v6.18 meldt nul errors en één stijlwaarschuwing voor een regel van
102 kolommen. De aanvullende spelling-/const-structlijsten waren niet aanwezig;
die twee controles zijn dus niet uitgevoerd. Zie [checkpatch.log](evidence/checkpatch.log).
De normale autotools-build en interne suites zijn native; de expliciete C-
binaries en nieuwe image-/foutsuites zijn daarnaast met sanitizers uitgevoerd.
Geen big-endian run, werkelijk power-cut hardwareproef, grote-volume-defrag,
TexFAT-, algemene vendor- of bad-clusterdefragkwalificatie wordt geclaimd.

## Onderzoeksfouten die niet als bewijs zijn meegeteld

De eerste driverfixture groeide van 4 naar 12 KiB en bleef bij 16-KiB clusters
ongedefragmenteerd. De fixture gebruikt nu de echte clustergrootte; iedere
uiteindelijke driverseed bewijst positieve beginfragmentatie. Een eerdere
modelgenerator gebruikte twee random groottes voor truncate; die uitvoering is
afgebroken en vervangen door de complete runs met één correcte truncategrootte.
Een aanvankelijk alleen in de root zoekende negatieve vendorproef is naar
recursieve directoryadressering aangepast. Geen van deze onvoltooide of foutieve
proeven is een PASS in de bovenstaande eindcijfers.

Een raw-worker-I/O-fout kan een inconsistente image achterlaten; een test die
hier toch een geldige eindimage eiste was te sterk voor dat mechanisme. De
herstelde foutpropagatie wordt daarom rechtstreeks getest, en de beloofde
byte-exacte veilige toestand via de journalinterface. Deze ervaring verklaart
waarom alleen lokale symptoomreparaties of een copywrapper onvoldoende zijn.

De modelbewijzen bevatten de bij de start vastgelegde bronhashes. Latere
uitbreidingen van testhulpcode staan daarnaast in environment.json. Het enige
latere operationele grensherstel opent bron- en journalbestanden met O_NONBLOCK,
zodat een FIFO vóór de reguliere-bestandscontrole niet kan blokkeren; dat is
native en onder sanitizers gericht getest, plus opnieuw in de korte smoketest.
Voor reguliere imagebestanden heeft die vlag geen effect. De geteste C-worker
en layoutparser zijn tijdens deze definitieve runs niet gewijzigd.
De releaseclaim blijft begrensd zoals in [ADR 0004](adr/0004-release.md).
