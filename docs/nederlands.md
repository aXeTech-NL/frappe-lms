# Nederlandse LMS-interface

Deze fork levert Nederlands (`nl`) via de standaard Frappe-vertalingen. Er is
geen afzonderlijke Nederlandse app, catalogus of runtimepatch nodig.

## Wat is vertaald?

- Alle 2.504 bestaande berichten in `lms/locale/nl.po` zijn ingevuld; de 1.005
  ontbrekende vertalingen zijn aangevuld. Ook aanvullende berichten uit de fork
  zijn opgenomen, waaronder cursusbeheer, Mijn toegang en de toegangsniveaukeuze.
- De belangrijkste navigatietermen zijn gecorrigeerd: **Cursussen**,
  **Lesgroepen**, **Leertrajecten**, **Toetsen**, **Cursisten**, **Docenten** en
  **Instellingen**.
- Maand- en dagnamen, relatieve tijden, 24-uursnotatie en de bestaande
  getal-/waarderingsformatters ondersteunen Nederlands. De bestaande afronding
  en de standaardweergave voor andere talen veranderen niet.
- De hoofdapp wacht op de vertalingen voordat componenten hun labels bepalen.
  Editor-subapps delen dezelfde vertalingen en hetzelfde lopende verzoek.
  Bij een mislukte vertaalopvraag blijft de Engelse terugval beschikbaar.
- Gebruikers zonder eigen taalkeuze gebruiken dezelfde taalresolutie als de
  LMS-shell: gebruikersvoorkeur, systeemtaal en de Frappe-terugval.

Dit vertaalt de **interface**, niet de door gebruikers geschreven cursussen,
lessen, toetsvragen, antwoorden of namen van toegangsniveaus. Teksten uit
andere apps en externe diensten blijven afhankelijk van hun eigen vertalingen.
Ook bestaande upstream-vertalingen kunnen nog redactionele verbeteringen nodig
hebben; een gevuld taalbestand is geen garantie dat elk dynamisch schermlabel
of elke toekomstige toevoeging vertaald is.

## Nederlands kiezen

Na installatie van de bijgewerkte fork:

1. Open het eigen profiel in LMS en kies **Edit Profile / Profiel bewerken**.
2. Kies bij **Language / Taal** Nederlands/Dutch (`nl`).
3. Sla op. De app herlaadt automatisch na een taalwijziging.

Voor een Nederlandse standaardtaal stelt een beheerder in Frappe **System
Settings → Language** in op `nl`. Een bestaande persoonlijke taalvoorkeur,
bijvoorbeeld `en`, blijft leidend. Verander die in het profiel als die gebruiker
ook Nederlands wil. Een andere taal kiezen blijft mogelijk.

## Installatie en uitrol

De bronwijziging alleen past een bestaande site niet aan. Voor de centrale
Helder-stack gelden de gewone afspraken: een exacte LMS-commit, een expliciet
geëxporteerde en geverifieerde Git-bundle voor ongepubliceerde code, en daarna een
afgestemde upgrade zonder reset. Geen sibling-worktree-mounts of losse patches.

Bij een goedgekeurde installatie op de doel-Bench moeten zowel frontendassets
als de gecompileerde vertalingen worden vernieuwd:

```sh
bench build --app lms
bench compile-po-to-mo --app lms --locale nl --force
bench --site <site> clear-cache
```

Frappe 16 leest de gecompileerde catalogus uit
`sites/assets/locale/nl/LC_MESSAGES/lms.mo`, niet rechtstreeks uit `nl.po`.
De PO/POT-bronbestanden zitten daarom ook in het package-manifest. Voer na de
normale upgrade/herstart een harde browserherlaadactie uit en controleer de
cursuslijst, een les, een toets, het profiel en Mijn toegang in Nederlands én
Engels. Deze wijziging activeert geen checkout, provider of abonnement.

Een bronwijziging of lokale test werkt de actieve dev-site niet automatisch bij.
De centrale stack documenteert de daadwerkelijk geïnstalleerde commit en taalkeuze
in zijn uitrolverslag. Behoud bij een upgrade bestaande persoonlijke taalvoorkeuren;
een Nederlandse systeemstandaard overschrijft die voorkeuren niet.

## Controles en onderhoud

Vanuit de repository, met Babel beschikbaar:

```sh
python -m unittest lms.tests.test_dutch_translations -v
cd frontend
yarn test src/tests/translation.test.ts src/tests/dutchLocale.test.ts
```

Zonder bestaande Python-omgeving kan de eerste opdracht met
`uv run --no-project --with babel python -m unittest lms.tests.test_dutch_translations -v`.

De catalogustests controleren dekking van `main.pot`, lege/fuzzy vertalingen,
interpolatievariabelen, e-mailsjabloonvariabelen en compilatie naar een bruikbare
gettext-catalogus. Frontendtests controleren de eerste render, gedeelde
verzoeken, foutafhandeling, Engelse terugval en Nederlandse datums/getallen.
Bij toekomstige upstream-updates moeten nieuwe berichten opnieuw worden
vertaald; verwijder fork-specifieke vermeldingen niet enkel omdat de upstream
POT ze nog niet bevat.
