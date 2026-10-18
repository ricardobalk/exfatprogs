# ADR 0003: kopiëren, onafhankelijk valideren en publiceren

Status: lokaal geïmplementeerd; niet door upstream geaccepteerd.

De workflow opent de bron uitsluitend O_RDONLY, zonder symlinkvolging, met
shared advisory flock en loopdetectie. De fd pint de inode. Alleen een reguliere
image binnen de hostsupportmatrix wordt geaccepteerd. Een reeds actieve
transactiemarker blokkeert de operatie.

Een private tijdelijke map (0700) komt in dezelfde parent als de output. De
kandidaat is 0600. Volledige bronbytes worden gekopieerd met short-I/O-controle
en kandidaat-fsync. Grootte/mtime/ctime worden daarna gecontroleerd. De
journalinterface bewerkt alleen deze kopie. Onafhankelijke reader plus fsck
controleren de kandidaat, inhoud en metadata moeten gelijk zijn en fragmentatie
moet nul zijn. Vóór publicatie wordt bovendien de volledige bron opnieuw gehasht.

Publicatie gebruikt `link(candidate, output)`: op hetzelfde filesystem is die
naamcreatie atomair en vervangt ze nooit een bestaande output, ook bij een race.
Na de link volgt fsync van de outputdirectory. Na opruimen van de private map
volgt opnieuw directory-fsync. Het gepubliceerde resultaat blijft privé (0600).

Vóór de link: fouten geven geen publieke output. Een kill kan private resten
achterlaten. Na de link: een mislukte directory-fsync kan een zichtbaar correct
bestand achterlaten zonder bevestigde durability; status 4 meldt dat expliciet.
Een kill op die grens laat eveneens mogelijk een zichtbaar bestand achter.
De workflow belooft dus geen afwezigheid van output na iedere fout. Hij belooft
een ongewijzigde bron en uitsluitend inhoudelijk geldige zichtbare kandidaten.
Cleanup verwijdert nooit een al gepubliceerde output.

Proceskills, kandidaatcorruptie, workerfouten, ENOSPC en alle wrapper-read-,
write-, publicatie- en directoryflushgrenzen zijn afzonderlijke proeven. Een
parentkill laat hoogstens werk aan de private kandidaat doorgaan; er bestaat
dan geen wrapper meer die nog kan publiceren. De workflow vervangt ADR 0002 niet.
