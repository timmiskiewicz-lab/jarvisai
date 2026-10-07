try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

from jarvisai.app import main

if __name__ == "__main__":
    main()
