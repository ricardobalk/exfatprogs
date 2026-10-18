# exFAT-defrag: herstel en experimentele imagekwalificatie

**BLUF:** de oorspronkelijke corrupties zijn reproduceerbaar gemaakt en de
allocatie- en writebackfouten zijn hersteld. Een Linux-imageinterface voegt
strikte preflight, een duurzaam extern undo-journal en gecontroleerd herstel toe.
Een aanvullende kopieerworkflow publiceert alleen onafhankelijk gevalideerde
resultaten. **Vrijgavestatus: functioneel hersteld binnen de beschreven scope,
experimenteel bruikbaar op wegwerpimages; niet vrijgegeven voor rechtstreeks
gebruik op gebruikersvolumes.** De gewone autotools-build blijft ongewijzigd.

Deze uitvoering gebruikt eigen bewijs. Cijfers uit `context/` zijn geen nieuwe
meetresultaten. De feitelijke resultaten en beperkingen staan in
[qualification.md](qualification.md); machineleesbaar bewijs staat onder
[evidence/](evidence/README.md). De aanpak volgt de scheiding tussen interface,
herstelprotocol, onafhankelijke tests en vrijgavebeleid van `feat/exfat-resize`,
zonder die branch in deze branch samen te voegen.

## Aanleiding en uitgangspunt

Basis: exfat-next-commit `1647ed54299ae8c4343a5edf40b892307f7e6459`.
De branch heet `fix/exfat-defrag`. Bij aanvang waren `context/` en `resize/`
ongetrackt; ze zijn niet in de patch opgenomen of overschreven. De upstream
README vraagt patches tegen exfat-next en Signed-off-by; beide zijn gevolgd.

[Issue 318](https://github.com/exfatprogs/exfatprogs/issues/318) bevat meldingen
van dataverlies en discussie over uitgestelde metadatawriteback. Dat zijn
onderzoeksaanwijzingen, geen verklaring van iedere individuele melding.
[Release 1.3.1](https://github.com/exfatprogs/exfatprogs/releases/tag/1.3.1)
vermeldt dat defrag wegens gemeld dataverlies uit de build is gehaald. De lokale
`Makefile.am` en `configure.ac` bevestigen dat dit op de gekozen basis nog zo is.
Een eigen `git ls-remote` controleerde tevens upstream master en exfat-next;
zie [sources.md](sources.md). Er is niets gepusht of gepubliceerd.

Het praktische resultaat is één extent per ondersteunde allocatie. Dat kan
bruikbaar zijn voor apparaten die aaneengesloten bestanden verwachten. Deze
uitvoering onderzoekt geen firmware van mediaspelers en bewijst geen defect in
zo'n apparaat.

## Onderdelen en verantwoordelijkheden

- [`defrag/defrag.c`](../../defrag/defrag.c): herstelde interne C-worker met
  cluster-swaps, virtuele ketenknopen en metadatawriteback. Het expliciete
  testbuildscript bouwt hem; rechtstreeks starten heeft **geen journal**.
- [`defrag/layout.py`](../../defrag/layout.py): begrensde preflight en vergelijking
  van inhoud, metadata, bootregio's en allocaties. Gebruikt geen C-parser.
- [`defrag/image_defrag.py`](../../defrag/image_defrag.py) en
  [`defrag/defrag.exfat`](../../defrag/defrag.exfat): Linux-imageinterface met
  lock, journal, commit en herstel. Dit is de experimentele operationele ingang.
- [`tests/defrag/image.py`](../../tests/defrag/image.py): onafhankelijke on-disk
  reader, plus modelgenerator. Importeert geen productieparser of C-mapping.
- [`tests/defrag/defrag_image.py`](../../tests/defrag/defrag_image.py): bron
  read-only openen, private kandidaat, journaled defrag, onafhankelijke reader
  en fsck, atomische publicatie zonder bestaande output te vervangen.

De C-worker blijft een intern experimenteel mechanisme. De journalinterface
maakt een protocol van de gehele bewerking; de writebackvolgorde van de worker
is op zichzelf geen crashherstelprotocol.

## Bevestigde defecten en oplossing

| Hypothese uit de opdracht | Bevinding op de basis | Herstel en gerichte proef |
| --- | --- | --- |
| Lege vendor-allocatie verschuift virtuele index | Bij lezen overgeslagen, bij schrijven geconsumeerd | Dezelfde selectie in beide passes; `empty-vendor-index` |
| Vendorchecksum vóór wijziging start/flags | Bevestigd | Checksum pas over uiteindelijke entry; `vendor-checksum` |
| Onvoltooide ketens ten onrechte contiguous | Bevestigd bij cancellation | NoFatChain uit actuele links; root blijft FAT-gestuurd; `interrupted-directory-fat` |
| Onderbroken systeemverplaatsing | Oorspronkelijke volgorde laat inconsistente toestand toe | Bitmap/upcase eerst afmaken, virtuele indexvolgorde behouden; `partial-system-relocation` |
| Directorywriteback volgt nieuwe FAT te vroeg | Bevestigd in dezelfde onderbrekingsreproducer | Nieuwe FAT vóór directorytraversal schrijven; rootsemantiek apart |
| Flush-/I/O-fouten niet juist verwerkt | Genegeerde directoryflush en fsync; EINTR niet herhaald | Flushstatus doorgeven, fsyncstatus controleren, EINTR herhalen; `directory-flush`, `fsync-status`, `eintr-read` |
| Bootsector-, endian- en grensfouten | 4096-byte sectorreproducer bevestigt verkeerde checksum/backupplaats | Alleen rootveld schrijven; logische sectorgeometrie; endianconversies; size_t vóór vermenigvuldiging; `logical-boot-sector` |
| Geen volledige ownershipcontrole | Onverklaarde allocatie wordt geaccepteerd | Eigendom/cycli/crosslinks vóór swaps; strikte hostpreflight; `unowned-allocation`, negatieve matrix |

Niet ieder onderdeel van een hypothese heeft een afzonderlijke historische
corruptiereproducer. FAT-volgorde en foutieve contiguous-aannames delen een
reproducer. Endianherstel en grotere rekenruimte zijn daarnaast code-inspectie;
er is geen big-endian hardwareproef. Het verslag maakt dit onderscheid expliciet.

De baselinebuild haalt **alle** betrokken C-bronnen en headers uit de vastgepinde
basis. Alleen de inmiddels verouderde aanroep van
`exfat_write_checksum_sector` krijgt het ontbrekende nul-offsetargument.
Er zijn geen gerepareerde gedeelde bibliotheken in die baseline gelinkt.
`build.py --baseline` bewaart de bronkopie en `baseline.json`.

## Ondersteuningsmatrix

| Structuur of situatie | Experimentele imageinterface |
| --- | --- |
| Linux, regulier bestand, één hardlink, geen symlink | Ondersteund; bestand via fd gepind |
| Volume vanaf byte nul, PartitionOffset=0, container exact volumegrootte | Ondersteund |
| Images groter dan 256 MiB; diskimages met partitietabel | Voor writes geweigerd |
| exFAT revisie 1.00, één FAT | Ondersteund |
| Twee FATs/TexFAT; dirty/media-failure/reserved flags | Voor writes geweigerd |
| FAT-bestanden en NoFatChain, inclusief stale FAT-waarden van NoFatChain | Ondersteund |
| Root, geneste en gefragmenteerde directories | Ondersteund tot diepte 128; root gebruikt altijd FAT |
| Lege bestanden, gedeeltelijke laatste clusters, valid-data-length | Ondersteund; logische bytes na VDL zijn nul |
| Unicode en meerdere naamentries | Ondersteund via UTF-16 en opgeslagen upcase-tabel; geen Unicode-normalisatie |
| Bitmap/upcase | Alleen aanvankelijk contiguous, complete FAT-ketens; beide worden gedefragmenteerd |
| Label, serial, attributen, timestamps en UTC-offsets | Behouden; bootregio's en genormaliseerde entrysets worden vergeleken |
| Volume-GUID-entry, vendor-extension-entry, TexFAT-padding, onbekende actieve entries | Voor writes geweigerd |
| Lege E1-vendorallocaties met niet-nul GUID | Ondersteund; geen allocatie of NoFatChain toegestaan |
| Gevulde E1-vendorallocaties | Alleen private fixture-GUID met bytes `00 01 ... 0f`; contract: opaque payload zonder fysieke verwijzingen |
| Willekeurige commerciële vendor-GUID met payload | Geweigerd; het formaat van eventuele interne clusterverwijzingen is onbekend |
| Bad clusters of onverklaarde bitmapallocaties | Voor writes geweigerd; registratie en volledige bron blijven ongewijzigd |
| Vol en één vrij cluster | Ondersteund: swaps hebben geen vrije volumecluster nodig; volledig extern journal wel |
| Fragmentatievrij volume | No-op; geen journal, marker of filesystemwrites |
| Blockdevices, loop-attached images | Geweigerd, ook bij alleen analyse |

De private vendor-GUID is uitsluitend een kwalificatiecontract; dit is geen
claim van ondersteuning voor alle vendorformaten. Bad-clustervolumes worden
nog niet gedefragmenteerd. Dat is een resterende scopebeperking van REQ-F03,
geen implementatie die slechte clusters als vrije bestemming gebruikt.

Voor een ondersteunde layout zonder bad clusters past de totale allocatie in
hetzelfde aantal clusters. De worker kan dus alle ketens achtereen aaneengesloten
plaatsen, ook bij een vol image. De interface accepteert een commit uitsluitend
als de nieuwe reader nul discontinuïteiten bevestigt. Er is geen gedeeltelijke
successtatus: cancellation herstelt de oude toestand; een I/O-fout vraagt herstel.

## Definitie van fragmentatie en behoud

Voor een niet-lege keten `c[0..n-1]` is een discontinuïteit een index `i` met
`c[i+1] != c[i]+1`. Het aantal extents is `1 + discontinuïteiten`. Lege ketens
hebben nul extents. De rapportage telt per allocatie en telt bestanden,
directories, vendorstreams en systeemstreams afzonderlijk als eigenaar.
Vrije ruimte tussen twee afzonderlijke bestanden is geen bestandsfragmentatie.
De interface rapporteert geen misleidend gewogen percentage van vrije ruimte.

De externe workload houdt bestandspaden en verwachte bytes bij; de onafhankelijke
reader controleert de geserialiseerde fixture vóór defrag tegen dat model.
Daarna vergelijkt hij inhoudshashes, bestandstypen en entrymetadata. VDL blijft
ongewijzigd: opslagbytes daarachter mogen bestaan, maar worden nooit als logische
bestandsinhoud geïnterpreteerd of door verhoogde VDL zichtbaar gemaakt.

Startclusters, FAT-links, de bitmap, NoFatChain en bijbehorende entry-/bootchecksums
mogen veranderen. Ze worden niet alleen uit een diff verwijderd: range, lengte,
exclusief eigendom, bitmapbereik, juiste ketensemantiek en checksums moeten zowel
voor als na geldig zijn. De bootvergelijking maskeert uitsluitend rootverwijzingen
en checksumsectoren; de reader valideert de gemaskeerde velden inhoudelijk.
Andere bootbytes, label en serial blijven behouden. Entryvergelijking maskeert
alleen allocatieverwijzingen, NoFatChain en de afhankelijk berekende checksum.
Een tweede interface-run moet het hele image byte-identiek laten.

## Bouwen en een korte smoketest

Dependencies: Linux, Python 3.11+ (`hashlib.file_digest`, `Random.randbytes`),
C-compiler, libc headers, libblkid development headers/library, GNU tar, xz,
xxd en de gebruikelijke autotools voor de normale upstream-build. Het hostfilesystem
moet advisory flock, user-xattrs, fsync en harde links ondersteunen. De journals
moeten buiten het te bewerken volume staan. Driverproeven vereisen bovendien
root/CAP_SYS_ADMIN, een Linux-exFAT-driver, mount/umount en losetup.

Vanaf de repositoryroot:

```sh
python3 tests/defrag/build.py --baseline
python3 tests/defrag/qualify.py --out defrag-test-results-smoke
```

`qualify.py` bouwt zelf expliciete testbinaries. De smoketest doet baseline-
reproducties, herstelde regressies, negatieve preflight en drie modelseeds.
Er wordt niets geïnstalleerd of aan de normale build toegevoegd.

## Analyse, uitvoering, herstel en kopieerworkflow

Gebruik uitsluitend zelf gemaakte wegwerpimages. De volgende commando's zijn
concrete interfacevoorbeelden, geen toestemming om een echt volume te proberen.

```sh
# Read-only analyse, JSON met discontinuïteiten, extents, haalbaarheid en beperkingen.
./defrag/defrag.exfat --dry-run /tmp/eigen-volume.img

# Alleen een nieuwe journalmap; geen bestaande map hergebruiken.
./defrag/defrag.exfat /tmp/eigen-volume.img --journal /tmp/eigen-defrag-journal

# Na status 3 of een kill: exact dezelfde inode en het originele journal.
./defrag/defrag.exfat /tmp/eigen-volume.img --recover --journal /tmp/eigen-defrag-journal

# Bron blijft read-only; resultaat mag nog niet bestaan.
python3 tests/defrag/defrag_image.py \
  --defrag build-defrag-tests/defrag.exfat \
  --fsck build-defrag-tests/fsck.exfat \
  /tmp/bron.img /tmp/gedefragmenteerd.img
```

De journalinterface vraagt beschikbare ruimte voor een volledige imagekopie plus
1 MiB marge. De wrapper heeft daarnaast de kandidaatkopie nodig. Een journal is
een private directory (0700) met reguliere bestanden (0600, één hardlink,
eigen gebruiker); symlinks worden geweigerd. Het protocol staat in
[ADR 0002](adr/0002-recovery.md).

| Exit | Betekenis |
| --- | --- |
| 0 | Analyse/no-op, volledige gevalideerde commit of voltooid herstel |
| 1 | Gestopt vóór actieve transactie; wrapper: kandidaat niet gepubliceerd |
| 2 | Ongeldige CLI-argumenten |
| 3 | Actieve of onleesbare transactiestatus: hersteldata behouden, expliciet herstellen |
| 4 | Commit of publicatie heeft plaatsgevonden, cleanup/durability niet volledig bevestigd; resultaat kan zichtbaar zijn |
| 130 / 143 | SIGINT / SIGTERM; vóór commit teruggerold, tijdens commitbatch kan de geldige nieuwe toestand behouden zijn; JSON/diagnostiek geeft toestand |

Een fout tijdens een aangevraagd herstel kan opnieuw status 3 opleveren. Dezelfde
undo-data blijven bruikbaar. Na duurzame markerverwijdering zijn eventuele
resterende journalbestanden stale: herstel weigert die zonder writes. Na een
volledig geslaagde cleanup is het journal verwijderd. Een herhaald herstelcommando
kan dus veilig weigeren; het mag geen tweede bewerking uitvoeren.

De signal handler registreert alleen het signaal. De gewone control flow wacht
op de C-worker en herstelt zo nodig de bron. De worker krijgt op Linux een
parent-death SIGKILL en erft de lockfd: een gecrashte host laat geen ongecontroleerd
schrijvende worker achter die het herstel inhaalt. Dit is afzonderlijk getest.
Tijdens undo wordt een tweede cancellation uitgesteld tot de oude toestand veilig
is hersteld. Een I/O-fout heeft voorrang op een cancellation-succesmelding.

Locks zijn advisory. Zichtbare loopattachments worden geweigerd, maar een andere
mountnamespace of een proces dat locks negeert kan niet betrouwbaar worden
uitgesloten. Offline/exclusief beheer is daarom een operationele voorwaarde;
er wordt geen afdwingbare exclusieve toegang geclaimd.

## Volledige kwalificatie en replay

```sh
# Volledig, inclusief native en ASan/UBSan, bestaande suite en driverproeven.
python3 tests/defrag/qualify.py --full --driver --jobs 4 \
  --out defrag-test-results-full

# Eén modelseed opnieuw, dezelfde geometrie/vendor-keuze uit seed afgeleid.
python3 tests/defrag/run.py --cases 1 --start-seed 73 --operations 5000 \
  --out defrag-test-results-replay-73

# Alle mutatiegrenzen van de kleine fixture en opnieuw onderbroken herstel.
python3 tests/defrag/faults.py --out defrag-test-results-faults

# Verlies/herordening/torn writes, apart van proceskills.
python3 tests/defrag/persistence.py --out defrag-test-results-persistence

# Alleen de werkelijke driverproef, in een private mountnamespace.
sudo python3 tests/defrag/mounted.py --seeds 10 --operations 5000 \
  --out defrag-test-results-driver
```

Elke outputmap moet nieuw zijn. `--build` selecteert een afwijkende expliciete
buildmap. De seeds, geometrie, iteraties, effectieve modelmutaties, echte
workload-OS-calls, fragmentatie, fsckstatus en foutposities worden machineleesbaar
vastgelegd. Modeliteraties tellen niet als Linux-filesystemoperaties. De
serializer doet image-I/O; dat maakt zijn 5.000 modelacties nog geen 5.000
kernel-driveracties. De driver telt de werkelijk uitgevoerde expliciete `os.*`
workloadcalls; runtime-, inspectie- en remountcalls staan buiten die teller.

Falen bewaart de private image(s), journals, acties, verwachte manifesten en
logs. Succesvolle rootless seeds verwijderen grote tijdelijke bestanden en
behouden hun caserecord. Foutinjectie bewaart geplande én bereikte posities.
Een positie die niet geraakt is, faalt de proef. Interpositie wordt alleen
bij de expliciet gestarte eigen C-testworker geladen.

`minimize.py --seed N --operations M --match 'exacte fouttekst' --out ...`
probeert halveringen van de workloadprefix met dezelfde seed en vereiste
foutdiagnostiek. Dit is een heuristische hulpmogelijkheid, geen claim van een
globaal minimale testcase of een uitgevoerde verkleining in het eindbewijs.

## Grenzen van het bewijs

Er is geen herstelgarantie tegen verlies/corruptie van zowel image als duurzaam
journal, een opslagapparaat dat over flush liegt, willekeurige torn hostmetadata,
malafide gelijktijdige schrijvers of hardwaredefecten. Het persistencemodel is
expliciet en afzonderlijk van werkelijk stroomverlies op een apparaat. Zie
[ADR 0002](adr/0002-recovery.md) en
[ADR 0004](adr/0004-release.md) voor de blokkades voor ruimere claims.
