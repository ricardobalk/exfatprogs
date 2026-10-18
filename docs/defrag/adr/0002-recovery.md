# ADR 0002: extern volledig undo-journal

Status: lokaal geïmplementeerd en volgens het beschreven model getest;
geen upstreamacceptatie of kwalificatie van blockdevices.

## Keuze en identiteit

Voor kleine offline images is een volledige preimage eenvoudiger te controleren
dan een nieuw clusterjournal. Het kost ongeveer één volledige image aan extra
opslag en maakt de herstelbeslissing onafhankelijk van mogelijk beschadigde
filesystemmetadata. De host is begrensd op 256 MiB en Linux-reguliere bestanden.
Er wordt geen prestatie- of schaalclaim voor echte kaarten gedaan.

Formaatversie 1 bestaat uit `preimage`, `manifest`, optioneel `commit.tmp` en
`commit`. Manifest en commit zijn canonieke ASCII-JSON-records met een SHA-256
van hun payload. Het manifest bindt apparaat/inode van het hostbestand, grootte,
oorspronkelijke volumeserial en volledige preimagehash aan een willekeurig
128-bit token. Het token staat tevens als `user.exfatprogs.defrag`-xattr op de
image-inode. Het journal is 0700; bestanden zijn 0600, eigen gebruiker, één link.
Alle bestanden en de directory worden zonder symlinkvolging geopend.

Een gekopieerd image heeft een andere inode; een oud journal heeft een ander
of ontbrekend token. Beide worden geweigerd. Voor herstel worden eerst alle
records en de gehele preimage, inclusief de opgeslagen serial, gecontroleerd.
Het live bootsector kan juist torn zijn; die is daarom geen herstelvoorwaarde.
Ontbrekende of onbetrouwbare hersteldata leiden tot stoppen, nooit gokken.

## Duurzame volgorde

1. Image openen en exclusieve advisory lock verkrijgen; loopattachments weigeren.
   Preflight en fsck zijn read-only. Geen marker of journal voor een afwijzing.
2. Nieuwe journalmap maken. Volledige preimage schrijven, short transfers en
   EINTR afhandelen; preimage fsync. Manifest schrijven en fsync.
3. Journaldirectory en zijn parent fsync: hersteldata en namen zijn duurzaam.
4. Uniek token aan image toevoegen en image fsync. Pas daarna worker starten.
5. Worker mag destructieve swaps en metadatawrites uitvoeren. Die hoeven
   tussentijds geen geldig mountbaar filesystem op te leveren. Het actieve
   token betekent dat uitsluitend herstel of de lopende host verder mag gaan.
6. Worker afsluiten, strikte semantische/allocatiecontrole en fsck uitvoeren.
   Image fsync: de volledige nieuwe toestand is duurzaam vóór commit.
7. Volledige nieuwe imagehash in `commit.tmp` schrijven, fsync, hernoemen naar
   `commit`, journaldirectory fsync. Dit is de duurzame commitgrens.
8. Token verwijderen, image fsync. Daarna pas recoverybestanden verwijderen,
   journaldirectory fsync, map verwijderen en parent fsync.

Een cancellation vóór de commitbatch brengt via gewone control flow de oude
bytes terug en flushes die. Tijdens de commitbatch wordt niet onder een mogelijk
gepubliceerd commitrecord teruggeschreven. Er wordt dan een geldige nieuwe
staat bevestigd of status 3/4 met hersteldata gerapporteerd. 130/143 blijven
herkenbaar als er een cancellationverzoek was.

## Herstelbeslissing en opnieuw crashen

Zonder `commit` worden de originele bytes uit de volledig geverifieerde
preimage teruggeschreven, geflusht en volledig teruggelezen/gehasht. Met een
`commit` wordt uitsluitend de nieuwe toestand geaccepteerd als token en
volledige imagehash overeenkomen. Een ongeldige commit is geen toestemming om
terug te rollen; het systeem stopt met hersteldata intact.

Herstel verandert de undo-bron niet. Een kill of EIO midden in undo laat het
actieve token en dezelfde preimage staan. Herhalen voert dezelfde idempotente
overschrijvingen uit. Na duurzame markerverwijdering hoeft niets meer aan de
image te worden hersteld. Een stale journal of een al verwijderde journalmap
wordt veilig geweigerd; herhaling hoeft geen tweede successtatus te geven.

De worker erft de flockfd en krijgt Linux PR_SET_PDEATHSIG=SIGKILL. De parent-
identiteit wordt na het instellen gecontroleerd. Herstel kan pas de lock nemen
wanneer de worker zijn fd's heeft gesloten. De test stopt een worker na een
write, doodt de host en controleert dat herstel vervolgens kan voltooien.

## Storage- en storingsmodel

Aangenomen: succesvolle fsync bewaart alle eerdere writes aan dat bestand;
directory-fsync bewaart de voorafgaande namespacewijzigingen; image-fsync
bewaart tevens zijn xattr. Duurzame journaldata worden niet daarna spontaan
beschadigd. Locks en offlinebeheer worden gerespecteerd. SHA-256 detecteert
accidentele corruptie, zonder authenticiteit tegen een kwaadwillende gebruiker.

Vóór image-fsync mogen imagewrites verloren gaan, worden herordend of gedeeltelijk
overleven. De replayproef gebruikt werkelijke workerwrites en test iedere
prefix, iedere halve write na een prefix, omgekeerde volgorden en deterministische
subsets. Alle toestanden vóór commit moeten naar exact de oude bytes herstellen.
Na image-fsync maar vóór duurzame commit is oud óf nieuw toegestaan: aanwezigheid
van een geldige commit kiest nieuw, ontbreken kiest oud. Na duurzame commit
is de volledige nieuwe toestand vereist. Proceskills testen daarnaast werkelijke
journals/markers/flushfouten, inclusief opnieuw gekilled herstel.

Dit model bewijst niet dat elk hostfilesystem en iedere controller die aannames
bij echt stroomverlies nakomt. Persistent EIO/ENOSPC kan herstel tijdelijk
blokkeren; de garantie is herstelbaarheid na het verdwijnen van de fout, niet
een succesvolle write naar defecte opslag. Verlies van journal én image,
corruptie van duurzaam journal, niet-gemodelleerde hostmetadata-tears en flushes
die onterecht succes rapporteren vallen buiten het model.

Afgewezen alternatief: alleen na iedere swap metadata bijwerken. Dat heeft
zonder atomair protocol nog steeds onderbrekingsvensters tussen data, FAT,
bitmap en directoryentries. Een kopiewrapper alleen beschermt evenmin een
rechtstreeks schrijvende engine.
