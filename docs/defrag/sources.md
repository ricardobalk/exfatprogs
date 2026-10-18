# Bronnen en herkomst

Gecontroleerd op 18 oktober 2026 (Europe/London).

- [Upstream issue 318](https://github.com/exfatprogs/exfatprogs/issues/318):
  meldingen en onderzoekshypothesen. Geen bewijs dat alle gemelde schade
  dezelfde oorzaak heeft.
- [Release 1.3.1](https://github.com/exfatprogs/exfatprogs/releases/tag/1.3.1):
  defrag tijdelijk buiten de build wegens gemeld dataverlies.
- [Microsoft exFAT specification](https://learn.microsoft.com/en-us/windows/win32/fileio/exfat-specification):
  primaire formaatbron voor geometrie, FAT, directories en checksums. De
  implementatie en onafhankelijke tests zijn eigen code. Er zijn geen gelekte
  implementaties geraadpleegd.
- Lokale upstream README, Makefile.am, configure.ac en de volledige datastroom
  in defrag.c/libexfat/exfat_dir: primaire basis voor de patch.

Een eigen, read-only controle:

```sh
git ls-remote https://github.com/exfatprogs/exfatprogs.git refs/heads/master refs/heads/exfat-next
```

Gaf op het onderzoeksmoment:

```text
1647ed54299ae8c4343a5edf40b892307f7e6459 refs/heads/exfat-next
8b427483164888f0a5af5e4ba92da4981f1094e2 refs/heads/master
```

De gekozen basis is dus de gecontroleerde exfat-next-tip; de meegeleverde
contextpatch is gebaseerd op de gecontroleerde master-tip. De patch is handmatig
aangepast voor de nieuwere I/O-statistiekpaden en exfat_fsync. De twee context-
patchbestanden hebben dezelfde inhoud. Bruikbare C-reparaties, fixturecode en
interpositie zijn overgenomen en vervolgens in deze uitvoering opnieuw getest.
De historische testcijfers zijn niet als eigen bewijs opgenomen.

Het full-image-journalpatroon is aangepast uit de lokale `feat/exfat-resize`
branch (`resize/image_resize.py`); de C-resizebibliotheek is niet geïmporteerd.
De commitreeks van resize is uitsluitend gelezen. De onafhankelijke defragreader
hergebruikt geen resize- of defrag-engineparser, serializer of virtuele mapping.
