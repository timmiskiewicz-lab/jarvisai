# JarvisAI

JarvisAI to lokalny asystent w stylu J.A.R.V.I.S. Działa w tle, sam dodaje się do autostartu i pokazuje okrągły HUD, który oddycha, gdy słucha, oraz powiększa się i zmniejsza, gdy mówi.

## Instalacja

Uruchom `JarvisAI-Setup.exe`. Po zbudowaniu leży w `dist/`. Ten sam plik jest w wydaniach GitHuba, bo ma ponad 100 MB i nie wchodzi do historii gita.

Instalator:

- kopiuje program do `%LOCALAPPDATA%\JarvisAI`
- dodaje wpis `JarvisAI` w autostarcie bieżącego użytkownika
- tworzy skróty w menu Start
- włącza aplikację

Zamknięcie okna chowa je do zasobnika. Wyłączenie jest w menu ikony przy zegarze.

## Mówienie

Powiedz **Hey Jarvis**. Odpowiada jedną z kwestii, na przykład „What's up, sir?”, „At your service.” albo „Yes, sir?”.

Potem możesz kazać mu odpalić zainstalowaną grę ze Steama:

- `launch Gothic 1`
- `play Portal 2`

Gdy na koncie jest więcej niż jeden profil Steama, pyta: „Which profile do you want me to launch, sir?” Odpowiedz `first`, `second` albo nazwą profilu. Jeśli profil nie jest tym, na którym Steam jest teraz zalogowany, Jarvis przełączy konto na czas uruchomienia gry. Steam musi mieć zapamiętane hasło tego profilu.

`cancel` przerywa wybór.

## Gemini

Program startuje tylko wtedy, gdy w zmiennych użytkownika jest `GEMINI_API_KEY`. Klucz nie trafia do plików projektu ani na GitHub. Jarvis wysyła do Gemini to, co usłyszał, i listę zainstalowanych gier, żeby wybrać właściwe polecenie.

## Głos

Głos jest już nagrany i wgrany w program. Klucz ElevenLabs nie jest potrzebny. Jeśli kiedyś wkleisz klucz w ustawieniach, nowe zdania mogą iść do głosu Daniel. Klucz zostaje tylko w `%APPDATA%\JarvisAI\config.json`.

## Co jest lokalne, a co idzie w sieć

- Hasło „Hey Jarvis” jest rozpoznawane lokalnie.
- Treść polecenia (na przykład nazwa gry) jest rozpoznawana lokalnie, a gdy to nie wystarczy, także przez Google po angielsku i po polsku.
- Gotowe odpowiedzi odtwarzają nagrania z programu. Zdania, których nie ma w nagraniach, dogrywa lokalny zapis albo, przy kluczu, ElevenLabs.

## Budowanie instalatora

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\build.ps1
```

Testy logiki Steama i komend:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_brain
```
