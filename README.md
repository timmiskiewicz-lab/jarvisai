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

Powiedz **Hey Jarvis**. Odpowiada dłuższą kwestią, na przykład „What's up, sir? What are you doing today?”.

Potem możesz kazać mu odpalić zainstalowaną grę ze Steama:

- `launch Gothic 1`
- `odpal Portal 2`
- `zainstaluj` albo `pobierz` grę, która jest w bibliotece, ale nie jest zainstalowana. Jarvis zaczyna pobieranie i mówi, o której powinno się skończyć.
- `play Bohemian Rhapsody by Queen` puszcza utwór na Spotify i mówi „Playing Bohemian Rhapsody by Queen, sir.”
- `play random song by Queen` wybiera losową piosenkę tego zespołu. Jak Spotify jest zainstalowany, otwiera aplikację. Jak nie ma aplikacji, otwiera stronę w przeglądarce.
- `Jarvis, turn this up` od razu podgłaśnia Windows o 10 procent. Działa też `louder`, `volume up` i `głośniej`.
- Można podać własną liczbę procent. `Jarvis, turn this up by 20 percent` podnosi o 20. Po polsku: `podgłośnij o 30 procent`. Na 100% Jarvis mówi, że głośniej już nie pójdzie.

Gdy na koncie jest więcej niż jeden profil Steama, pyta: „Which profile do you want me to launch, sir?” Odpowiedz `first`, `second` albo nazwą profilu. Jeśli profil nie jest tym, na którym Steam jest teraz zalogowany, Jarvis przełączy konto na czas uruchomienia gry. Steam musi mieć zapamiętane hasło tego profilu.

`cancel` przerywa wybór.

## Gemini

Klucz API wkleja się w ustawieniach aplikacji. Jarvis sam zapisuje go w zmiennej użytkownika `GEMINI_API_KEY`. Klucz nie trafia do folderu programu ani do repozytorium. Jarvis wysyła do Gemini to, co usłyszał, i listę gier ze Steama, żeby wybrać właściwe polecenie.

### Skąd wziąć klucz

1. Wejdź na [Google AI Studio](https://aistudio.google.com/apikey) i zaloguj się kontem Google.
2. Wybierz **Create API key**.
3. Wskaż projekt Google Cloud albo utwórz nowy, gdy Studio o to poprosi.
4. Skopiuj klucz.

### Wklejenie klucza w Jarvisie

1. Uruchom **JarvisAI**. Przy pierwszym uruchomieniu, gdy klucza jeszcze nie ma, okno ustawień otwiera się samo.
2. Możesz je też otworzyć później ikoną zębatki w prawym górnym rogu HUD-a.
3. W polu **Gemini API key** wklej skopiowany klucz.
4. Naciśnij **Save**.

Po zapisie program wpisuje klucz do zmiennej użytkownika `GEMINI_API_KEY`, tak jak klucz ElevenLabs zapisuje się z poziomu aplikacji. Jarvis od razu z niego korzysta. Wyłączenie i ponowne włączenie programu nie jest potrzebne. Pole **ElevenLabs API key** pod spodem jest opcjonalne i dotyczy tylko głosu, nie Gemini.

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
