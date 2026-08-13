# -*- coding: utf-8 -*-
"""
categorias.py — taxonomía de la biblioteca y clasificador automático.

6 categorías grandes, cada una con sus subcategorías. Cada modelo se
clasifica leyendo su nombre y su ruta (español / inglés / portugués,
que es como vienen los archivos descargados).

Si el usuario corrige la categoría de un modelo en la app, esa corrección
manda siempre por sobre lo automático.
"""
import re, unicodedata

# Cada vez que se cambie cómo se clasifica, hay que SUBIR este número.
# La app lo compara con el que quedó guardado al indexar y, si no calza,
# vuelve a ordenar los modelos sola. Sin esto, mejorar las categorías no
# cambia nada en el computador del usuario hasta que reindexe a mano.
VERSION_CLASIFICADOR = 2

# ---------------------------------------------------------------------------
# (subcategoría, [palabras clave])  — se evalúan en orden dentro de cada grupo
# ---------------------------------------------------------------------------
TAXONOMIA = {
    "Vehículos": [
        ("Aéreos", ["avion", "aviao", "aeroplano", "airplane", "plane", "biplano", "biplane",
                    "helicoptero", "helicopter", "jet", "caza", "spitfire", "cessna", "boeing",
                    "airbus", "planeador", "glider", "dron", "drone", "globo aerostatico",
                    "zeppelin", "dirigible", "nave espacial", "spaceship", "cohete", "rocket",
                    "shuttle", "transbordador", "ovni", "ufo", "x wing", "xwing", "tie fighter",
                    "millennium", "halcon milenario", "apollo", "satelite"]),
        ("Acuáticos", ["barco", "barca", "bote", "boat", "ship", "velero", "sailboat", "yate",
                       "yacht", "lancha", "canoa", "kayak", "submarino", "submarine", "titanic",
                       "galeon", "goleta", "fragata", "pirata", "navio", "buque", "catamaran",
                       "balsa", "remolcador", "portaaviones"]),
        ("Motos y bicis", ["moto", "motocicleta", "motorcycle", "bike", "bicicleta", "bicycle",
                           "chopper", "harley", "scooter", "vespa", "cuatrimoto", "quad",
                           "triciclo", "monociclo"]),
        ("Autos", ["auto", "carro", "coche", "car ", "automovil", "deportivo", "coupe",
                   "combi", "dragster", "sedan", "camioneta", "pickup", "convertible",
                   "roadster", "rally", "nascar", "taxi", "limusina", "ferrari",
                   # ojo: "escarabajo"/"beetle" solos son el INSECTO; el auto va con marca
                   "vw beetle", "escarabajo vw", "volkswagen escarabajo", "vocho",
                   "lamborghini", "porsche", "mustang",
                   "jeep", "buggy", "kart", "formula 1", "f1 ", "hot rod", "muscle car",
                   "corvette", "camaro", "delorean", "batimovil", "batmobile", "volkswagen",
                   "mercedes", "bmw", "audi", "toyota", "nissan", "chevrolet", "ford "]),
        ("Camiones y maquinaria", ["camion", "truck", "tractor", "excavadora", "escabadora",
                                   "escavadora", "excavator", "retroexcavadora", "topadora",
                                   "hormigonera", "volquete", "cisterna", "carreta",
                                   "carreton", "carro de mano", "carruaje", "coche de caballos",
                                   "bulldozer", "grua", "crane", "retroexcavadora", "montacargas",
                                   "forklift", "bus", "autobus", "micro", "furgon", "van ",
                                   "ambulancia", "bombero", "fire truck", "patrulla", "policia",
                                   "cosechadora", "arado", "maquinaria"]),
        ("Trenes", ["tren", "train", "locomotora", "locomotive", "ferrocarril", "vagon",
                    "railway", "railroad", "tranvia", "metro "]),
        ("Militares", ["tanque", "tank", "blindado", "militar", "military", "acorazado",
                       "canon", "artilleria"]),
    ],
    "Animales": [
        ("Insectos y arácnidos", ["insecto", "insect", "abeja", "bee", "biene", "mariposa",
                                  "escarabajo", "beetle", "bicho", "ciervo volante",
                                  "butterfly", "borboleta", "libelula",
                                  "dragonfly", "arana", "spider", "escorpion", "alacran",
                                  "scorpion", "hormiga", "ant ", "avispa", "grillo", "mantis",
                                  "saltamontes", "mosca", "mosquito", "cucaracha", "ciempies",
                                  "caracol", "snail", "oruga", "gusano"]),
        ("Dinosaurios", ["dino", "dinosaur", "rex", "raptor", "saurus", "saurio", "saur",
                         "ssauro", "sauro", "ceratops", "ceratopsier", "brachiosaur",
                         "braciossaurus", "brontossaurus", "brontosaurio", "triceratops",
                         "pterodactilo", "mamut", "mammoth", "prehistoric", "jurassic",
                         "estegosaurio", "braquiosaurio", "velociraptor", "apatosaurus",
                         "diplodocus", "ankylosaurus", "allosaurus", "parasaurolophus"]),
        ("Aves", ["ave", "aves", "bird", "pajaro", "passaro", "carpintero", "woodpecker",
                  "aguila", "agila", "aguia",
                  "eagle", "buho", "owl", "lechuza", "coruja", "loro", "papagayo", "parrot",
                  "colibri", "hummingbird", "gallo", "gallina", "rooster", "pato", "duck",
                  "cisne", "swan", "flamenco", "flamingo", "pinguino", "penguin", "tucan",
                  "halcon", "gaviota", "cuervo", "raven", "paloma", "pavo real", "peacock",
                  "condor", "golondrina", "pelicano", "avestruz", "colibrí"]),
        ("Marinos", ["pez", "peces", "fish", "peixe", "tiburon", "shark", "delfin", "dolphin",
                     "ballena", "whale", "pulpo", "octopus", "calamar", "medusa", "jellyfish",
                     "tortuga marina", "caballito de mar", "seahorse", "cangrejo", "crab",
                     "langosta", "estrella de mar", "starfish", "concha", "coral", "orca",
                     "manta raya", "foca", "morsa"]),
        ("Mascotas", ["perro", "dog", "cachorro", "puppy", "cao", "gato", "cat ", "gatito",
                      "kitten", "conejo", "rabbit", "bunny", "hamster", "cobayo", "loro mascota",
                      "pez dorado", "husky", "bulldog", "labrador", "pastor aleman", "chihuahua",
                      "poodle", "beagle", "dachshund", "corgi"]),
        ("Salvajes", ["leon", "lion", "tigre", "tiger", "elefante", "elephant", "jirafa",
                      "giraffe", "cebra", "zebra", "mono", "monkey", "gorila", "oso", "bear",
                      "lobo", "wolf", "zorro", "fox", "ciervo", "deer", "venado", "alce",
                      "rinoceronte", "hipopotamo", "canguro", "koala", "panda", "leopardo",
                      "jaguar", "puma", "guepardo", "camello", "llama", "alpaca", "murcielago",
                      "bat ", "ardilla", "squirrel", "erizo", "mapache", "castor", "nutria",
                      "serpiente", "snake", "cobra", "vibora", "boa", "piton",
                      "cocodrilo", "caiman", "lagarto", "iguana", "camaleon",
                      "rana", "frog", "sapo", "tortuga", "turtle", "caballo", "horse", "vaca",
                      "cow ", "toro", "bull", "cerdo", "pig ", "oveja", "sheep", "cabra",
                      "burro", "ciervo", "reno", "bisonte", "unicornio", "dragon", "fenix"]),
    ],
    "Hogar y muebles": [
        ("Cajas y organizadores", ["caja", "cajas", "box ", "boxes", "cofre", "chest", "baul",
                                   "organizador", "organizer", "porta", "holder", "soporte",
                                   "stand", "estuche", "case ", "joyero", "alcancia", "hucha",
                                   "piggy bank", "bandeja", "tray", "canasta", "cesta", "basket",
                                   "contenedor", "almacenamiento", "storage", "gaveta"]),
        ("Muebles", ["mueble", "furniture", "silla", "chair", "mesa", "table", "escritorio",
                     "desk", "estante", "shelf", "repisa", "librero", "bookshelf", "banco",
                     "bench", "taburete", "stool", "cama", "bed ", "sofa", "closet", "armario",
                     "ropero", "comoda", "velador", "perchero", "percha", "hanger",
                     "cuna", "berco", "moveis", "movel", "banheiro", "cadeira", "mesita",
                     "aparador", "vitrina", "mueble bano", "zapatero", "escalera"]),
        ("Cocina", ["cocina", "kitchen", "posavaso", "coaster", "individual", "mantel",
                    "servilletero", "napkin", "especiero", "tabla de picar", "cutting board",
                    "utensilio", "cuchara", "tenedor", "plato", "taza", "mug ", "vaso",
                    "botella", "bottle", "copa", "wine", "vino", "cerveza", "beer", "bar ",
                    "delantal", "recetario", "azucarero", "panera", "frutero"]),
        ("Lámparas y luz", ["lampara", "lamp", "luminaria", "luz", "light", "led ", "farol",
                            "linterna", "candelabro", "vela", "candle", "portavela", "velador luz",
                            "night light", "luz nocturna", "aplique"]),
        ("Relojes", ["reloj", "clock", "relogio", "cucu", "cuco", "pendulo", "despertador",
                     "reloj de pared", "reloj de arena"]),
        ("Decoración", ["decoracion", "decor", "adorno", "ornamento", "cuadro", "marco",
                        "frame", "portarretrato", "espejo", "mirror", "florero", "jarron",
                        "vase", "macetero", "maceta", "planter", "movil", "colgante",
                        "guirnalda", "centro de mesa", "separador", "biombo", "mandala",
                        "vitral", "tapiz", "mural"]),
    ],
    "Juegos y juguetes": [
        ("Puzzles y rompecabezas", ["puzzle", "puzzles", "rompecabeza", "quebra cabeca",
                                    "tangram", "cubo rubik", "laberinto", "maze", "encastre",
                                    "3d puzzle", "puzle"]),
        ("Autómatas y mecánicos", ["automata", "automaton", "mecanismo", "mechanism", "engranaje",
                                   "gear", "leva", "kinetic", "cinetico", "movimiento",
                                   "manivela", "crank", "marble", "canica", "rube goldberg"]),
        ("Juegos de mesa", ["ajedrez", "chess", "damas", "checkers", "domino", "backgammon",
                            "ludo", "parchis", "gato", "tic tac toe", "tres en raya", "dado",
                            "dice", "naipe", "carta", "poker", "tablero", "board game",
                            "memoria", "loteria", "bingo", "jenga", "torre"]),
        ("Figuras y personajes", ["figura", "figure", "muneco", "muneca", "doll", "robot",
                                  "personaje", "character", "superheroe", "superhero", "batman",
                                  "spiderman", "superman", "marvel", "star wars", "pokemon",
                                  "mario", "sonic", "anime", "manga", "funko", "minion",
                                  "disney", "princesa", "soldado", "caballero", "knight",
                                  "vikingo", "pirata figura", "zombie", "calavera", "skull",
                                  "esqueleto", "monstruo"]),
        ("Juguetes", ["juguete", "toy", "toys", "carrusel", "carrucel", "carousel",
                      "rueda de la fortuna", "vuelta al mundo", "noria",
                      "trompo", "yoyo", "balancin", "sonajero",
                      "cochecito", "casa de munecas", "dollhouse", "tren de juguete",
                      "pista", "circuito", "titere", "marioneta"]),
    ],
    "Casas y maquetas": [
        ("Casas", ["casa", "casita", "house", "home", "hogar maqueta", "cabana", "cabin",
                   "chalet", "villa", "mansion", "casa de campo", "casa del arbol", "treehouse",
                   "casa de pajaros", "birdhouse", "casita de aves", "comedero"]),
        ("Edificios y monumentos", ["edificio", "building", "torre", "tower", "rascacielos",
                                    "iglesia", "church", "catedral", "templo", "mezquita",
                                    "monumento", "eiffel", "coliseo", "piramide", "pyramid",
                                    "taj mahal", "big ben", "bigben", "burj", "hotel",
                                    "basilica", "santuario", "station", "estacion",
                                    "estatua", "faro", "lighthouse",
                                    "molino", "windmill", "puente", "bridge", "arco"]),
        ("Castillos y fantasía", ["castillo", "castle", "fortaleza", "fort", "medieval",
                                  "torre de vigilancia", "aldea", "village", "pueblo",
                                  "hobbit", "elfico", "magico"]),
        ("Maquetas y arquitectura", ["maqueta", "model kit", "architectural", "arquitectura",
                                     "plano", "diorama", "escala", "scale model", "layout",
                                     "terreno", "paisaje"]),
    ],
    "Arte y ocasiones": [
        ("Navidad", ["navidad", "navideno", "christmas", "natal", "arbol de navidad",
                     "santa", "papa noel", "reno navidad", "pesebre", "nacimiento",
                     "corona navidad", "copo de nieve", "snowflake", "adorno navideno"]),
        ("Religioso", ["religioso", "cruz", "cross", "crucifijo", "jesus", "cristo", "virgen",
                       "maria", "angel", "santo", "biblia", "rosario", "iglesia adorno",
                       "budista", "buda", "om ", "mandala religioso"]),
        ("Mandalas y geometría", ["mandala", "geometrico", "geometric", "fractal", "voronoi",
                                  "parametrico", "patron", "pattern", "celosia", "rejilla",
                                  "grid", "espiral", "flor de la vida", "simetria"]),
        ("Letreros y carteles", ["letrero", "cartel", "sign ", "signo", "letra", "letras",
                                 "letter", "abecedario", "alfabeto", "nombre", "monograma",
                                 "logo", "placa", "senal", "bienvenido", "welcome", "frase",
                                 "cita", "quote", "numero", "numeros"]),
        ("Joyas y accesorios", ["joya", "jewel", "jewellery", "jewelry", "arete", "aro ",
                                "pendiente", "earring", "collar", "necklace", "colgante joya",
                                "pulsera", "bracelet", "anillo", "ring ", "broche", "llavero",
                                "keychain", "chaveiro", "pin ", "boton", "hebilla", "peineta",
                                "gemelos", "reloj pulsera"]),
        ("Fechas especiales", ["san valentin", "valentine", "amor", "love", "corazon", "heart",
                               "dia de la madre", "dia del padre", "cumpleanos", "birthday",
                               "boda", "wedding", "novios", "aniversario", "graduacion",
                               "halloween", "calabaza", "pumpkin", "pascua", "easter",
                               "conejo pascua", "huevo", "fiestas patrias", "año nuevo"]),
    ],
}

# pistas por carpeta del disco (peso alto: el papá ya las había ordenado así)
PISTAS_RUTA = {
    "vehiculo": ("Vehículos", None), "vehiculos": ("Vehículos", None),
    "vehiculos y transporte": ("Vehículos", None), "transporte": ("Vehículos", None),
    "animales": ("Animales", None), "animal": ("Animales", None),
    "insectos": ("Animales", "Insectos y arácnidos"),
    "aves": ("Animales", "Aves"), "dinosaurios": ("Animales", "Dinosaurios"),
    "marinos": ("Animales", "Marinos"), "mascotas": ("Animales", "Mascotas"),
    "hogar": ("Hogar y muebles", None), "muebles": ("Hogar y muebles", "Muebles"),
    "cocina": ("Hogar y muebles", "Cocina"), "lamparas": ("Hogar y muebles", "Lámparas y luz"),
    "juguetes": ("Juegos y juguetes", None), "puzzles": ("Juegos y juguetes", "Puzzles y rompecabezas"),
    "rompecabezas": ("Juegos y juguetes", "Puzzles y rompecabezas"),
    "maquetas": ("Casas y maquetas", "Maquetas y arquitectura"),
    "edificios": ("Casas y maquetas", "Edificios y monumentos"),
    "castillos": ("Casas y maquetas", "Castillos y fantasía"),
    "navidad": ("Arte y ocasiones", "Navidad"), "religiosos": ("Arte y ocasiones", "Religioso"),
    "mandalas": ("Arte y ocasiones", "Mandalas y geometría"),
    "letreros": ("Arte y ocasiones", "Letreros y carteles"),
    "cajas": ("Hogar y muebles", "Cajas y organizadores"),
    "cajas para vinos y licores": ("Hogar y muebles", "Cocina"),
    "cosina y decoracion": ("Hogar y muebles", "Decoración"),
    "cocina y decoracion": ("Hogar y muebles", "Decoración"),
    "decoracion": ("Hogar y muebles", "Decoración"),
    "relojes": ("Hogar y muebles", "Relojes"),
    "casas": ("Casas y maquetas", "Casas"),
    "juegos": ("Juegos y juguetes", None),
    "automatas": ("Juegos y juguetes", "Autómatas y mecánicos"),
    "personajes y figuras": ("Juegos y juguetes", "Figuras y personajes"),
    "joyas": ("Arte y ocasiones", "Joyas y accesorios"),
    "navidad y religiosos": ("Arte y ocasiones", "Navidad"),
    "mandalas y vectores muro": ("Arte y ocasiones", "Mandalas y geometría"),
}

ORDEN = ["Vehículos", "Animales", "Hogar y muebles", "Juegos y juguetes",
         "Casas y maquetas", "Arte y ocasiones", "Otros"]

SUBS_OTROS = ["Utilidades láser", "Sin clasificar"]

# ajustes del láser, plantillas de potencia, tests de material...
CLAVES_UTILIDADES = ["utilidad", "plantilla", "template", "test", "prueba de material",
                     "potencia", "power", "escala de grises", "grayscale", "calibracion",
                     "ajuste", "setting", "material test", "kerf", "tabla", "chart",
                     "cnc router", "gcode", "grbl", "lightburn", "falcon", "regla",
                     "medidor", "calibre", "muestrario"]


def _n(s):
    """minúsculas sin tildes, con espacios a los lados para buscar palabras."""
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[_\-/\\.,()\[\]]+", " ", s)
    return " " + re.sub(r"\s+", " ", s).strip() + " "


def _pos(texto, palabra):
    """Dónde aparece la palabra en el texto, o -1 si no está.

    Acepta la palabra completa y también su plural o forma alargada
    ('avion' encuentra 'aviones'), pero NO permite que un pedazo corto pegue
    dentro de otra palabra ('car' ya no encuentra 'carpintero').
    """
    p = palabra.strip()
    if not p:
        return -1
    exacta = texto.find(" " + p + " ")
    if exacta >= 0:
        return exacta
    if len(p) < 4:          # palabras cortas: solo coincidencia exacta
        return -1
    # plural / forma alargada: la palabra del texto empieza con la clave
    i = texto.find(" " + p)
    while i >= 0:
        resto = texto[i + 1 + len(p):]
        sigue = resto.split(" ", 1)[0]
        if len(sigue) <= 2:   # "aviones" = avion + "es", "cajas" = caja + "s"
            return i
        i = texto.find(" " + p, i + 1)
    return -1


def _tiene(texto, palabra):
    return _pos(texto, palabra) >= 0


def _por_palabras(texto):
    """(categoria, subcategoria) según las palabras clave que aparezcan.

    Gana la que aparece ANTES en el nombre, porque en los nombres de modelos el
    objeto principal va primero ("Caja corazón" es una caja, no un corazón).
    Si dos empiezan en el mismo punto, gana la más larga (más específica).
    """
    mejor = None   # (posicion, -largo, cat, sub)
    for cat, subs in TAXONOMIA.items():
        for sub, claves in subs:
            for k in claves:
                p = k.strip()
                if not p:
                    continue
                pos = _pos(texto, p)
                if pos < 0:
                    continue
                cand = (pos, -len(p), cat, sub)
                if mejor is None or cand < mejor:
                    mejor = cand
    return (mejor[2], mejor[3]) if mejor else None


def _bonito(s):
    s = re.sub(r"[_]+", " ", str(s or "")).strip()
    s = re.sub(r"\s+", " ", s)
    return (s[:1].upper() + s[1:]) if s else s


def clasificar(nombre, ruta_partes):
    """Devuelve (categoria, subcategoria).

    MANDA LA CARPETA DEL USUARIO: si el modelo está dentro de una carpeta que
    reconocemos (ej. "Vehiculos"), esa es la categoría, y la subcarpeta
    siguiente se usa tal cual como subcategoría (ej. "Autos", "Barcos").
    Solo cuando la carpeta no dice nada se adivina por el nombre.
    """
    partes = list(ruta_partes or [])
    txt_nombre = _n(nombre)
    texto = txt_nombre + _n(" ".join(partes))

    # 1) LA ORGANIZACIÓN DEL USUARIO MANDA
    for i, parte in enumerate(partes):
        p = _n(parte).strip()
        if p not in PISTAS_RUTA:
            continue
        cat, sub_fija = PISTAS_RUTA[p]
        if sub_fija:
            return cat, sub_fija
        # su subcarpeta siguiente es la subcategoría, con el nombre que él le puso
        if i + 1 < len(partes):
            sub = partes[i + 1].strip()
            if sub and _n(sub).strip() != txt_nombre.strip():
                return cat, _bonito(sub)
        # no hay subcarpeta: afinamos con las palabras, pero sin salirnos de la categoría
        r = _por_palabras(texto)
        if r and r[0] == cat:
            return r
        return cat, TAXONOMIA[cat][0][0]

    # 2) utilidades / plantillas del láser
    for k in CLAVES_UTILIDADES:
        if _tiene(texto, k):
            return "Otros", "Utilidades láser"

    # 3) adivinar por el nombre del modelo
    r = _por_palabras(txt_nombre)
    if r:
        return r

    # 4) último intento: con toda la ruta
    r = _por_palabras(texto)
    if r:
        return r

    return "Otros", "Sin clasificar"


def estructura():
    """Para la interfaz: categorías grandes con sus subcategorías."""
    out = []
    for cat in ORDEN:
        if cat == "Otros":
            out.append({"nombre": cat, "subs": SUBS_OTROS})
        else:
            out.append({"nombre": cat, "subs": [s for s, _ in TAXONOMIA[cat]]})
    return out
