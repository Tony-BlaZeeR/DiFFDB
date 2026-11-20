import dataclasses
import logging

import qtawesome as qta

from diffdb import i18n, keystore, preferences, theme, updates
from diffdb.about_dialog import mostra_info
from diffdb.choose_tab import ChooseTab
from diffdb.connections import load_connections, save_connections, usa_portachiavi
from diffdb.dialogs import ask_connection
from diffdb.diff_DB import compare_snapshots
from diffdb.filters_dialog import modifica_filtri as _chiedi_filtri
from diffdb.home_tab import HomeTab
from diffdb.paths import config_dir, resource_path
from diffdb.qt import Qt, QtCore, QtGui, QtWidgets, bind_children, load_ui
from diffdb.report import slug, write_excel, write_sql
from diffdb.results_tab import ResultsTab
from diffdb.rules import (
    NESSUNA,
    NOME_PREDEFINITO,
    RegoleNonValide,
    carica,
    cerca,
    chiave,
    salva,
)
from diffdb.snapshot_io import SnapshotFile
from diffdb.urls import mask_password, password_letterale, sanitize
from diffdb.widgets import Riquadro, WordmarkGradiente, logo_pixmap
from diffdb.worker import CompareWorker, SnapshotWorker, UpdateCheckWorker

logger = logging.getLogger(__name__)


def _icon_color() -> str:
    """Colore delle icone qtawesome: segue il tema attivo."""
    return theme.corrente().get("text2", "#A9B7C6")


TAB_HOME, TAB_CONFIGURAZIONE, TAB_SCELTA, TAB_RISULTATI = range(4)
COL_NAME, COL_STRING, COL_PASSWORD, COL_SCHEMA, COL_EDIT, COL_DELETE = range(6)

# Con quale nome si salvano le larghezze delle colonne, e quali colonne ha
# senso ricordare: quelle dei pulsanti si dimensionano da sole sulle icone.
NOME_COLONNE_CONNESSIONI = "connessioni"
LARGHE_CONNESSIONI = (COL_NAME, COL_STRING, COL_PASSWORD, COL_SCHEMA)

# La colonna che assorbe lo spazio liberato da una regolazione a mano: la
# stringa di connessione e' quella lunga, le altre hanno misure prevedibili.
COL_ELASTICA = COL_STRING

# Sotto questa larghezza una colonna non si legge: si tiene il minimo e si
# lascia comparire la barra di scorrimento orizzontale.
MINIMO_COLONNA = 60

# --- ridimensionamento della finestra senza cornice ------------------------

# Quanto e' spesso il bordo che risponde al ridimensionamento. Sotto i 4 px
# diventa difficile da agganciare col mouse, sopra gli 8 si fa fatica a
# cliccare quello che gli sta vicino.
MARGINE_RESIZE = 6

# Che cursore mostrare per ogni combinazione di bordi. Scritta per esteso
# invece di dedurla dai flag: con otto casi la mappa si legge e si verifica,
# il calcolo sui bit no.
_SX = Qt.Edge.LeftEdge
_DX = Qt.Edge.RightEdge
_SU = Qt.Edge.TopEdge
_GIU = Qt.Edge.BottomEdge
FORME_CURSORE = {
    _SX.value: Qt.CursorShape.SizeHorCursor,
    _DX.value: Qt.CursorShape.SizeHorCursor,
    _SU.value: Qt.CursorShape.SizeVerCursor,
    _GIU.value: Qt.CursorShape.SizeVerCursor,
    (_SX | _SU).value: Qt.CursorShape.SizeFDiagCursor,
    (_DX | _GIU).value: Qt.CursorShape.SizeFDiagCursor,
    (_DX | _SU).value: Qt.CursorShape.SizeBDiagCursor,
    (_SX | _GIU).value: Qt.CursorShape.SizeBDiagCursor,
}

# Gli unici eventi che ci interessano. Il filtro sta sull'applicazione e vede
# passare tutto, percio' lo scarto deve costare il meno possibile.
_EVENTI_MOUSE = frozenset((QtCore.QEvent.Type.MouseMove,
                           QtCore.QEvent.Type.MouseButtonPress))

# Minimo della finestra. Era 800x600, mentre il layout ci sta in molto meno:
# su uno schermo basso quell'altezza costringeva a tenere la finestra piu'
# alta dello spazio utile. Non si scende fino al minimo che calcola Qt perche'
# quello cambia con il contenuto e con la scheda aperta - misurati 393 e 445
# in due stati diversi della stessa finestra - e arrivare al pelo vorrebbe
# dire ritrovarsi con qualcosa tagliato in uno stato che non avevamo
# misurato. Cosi' restano cento pixel di margine su quanto visto, e cento di
# liberta' in piu' rispetto a prima.
MINIMO_LARGHEZZA = 800
MINIMO_ALTEZZA = 500


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self.drag_position = None
        self.scanline = None
        self.pulsante_colore = None
        self.connections = []
        self.thread = None
        self.worker = None
        self._ultimo_diff = None
        self._colonne_conn_sistemate = False
        self._cursore_bordo = None
        self._filtro_bordi_attivo = False
        self._sto_sistemando_conn = False
        self._proporzioni_conn = None
        self._upd_thread = None
        self._upd_worker = None
        self.output_dir = preferences.cartella_output(str(config_dir()))
        self.regole = _carica_regole()

        self._ui = load_ui(resource_path("ui", "main_window.ui"))
        self.setCentralWidget(self._ui.centralWidget())
        bind_children(self.centralWidget(), self)
        # Solo il minimo: il .ui dichiarava minimo e massimo uguali, e la finestra
        # non si poteva ridimensionare — con un albero a cinque colonne era un problema.
        self.setMinimumSize(MINIMO_LARGHEZZA, MINIMO_ALTEZZA)
        self.resize(self._ui.size())

        # Lo stile e' dell'applicazione (vedi app.py / theme.applica), cosi' vale
        # anche per le finestre di dialogo native e si puo' cambiare a caldo.

        self.setWindowTitle("DiFFDB")
        self.setWindowIcon(QtGui.QIcon(resource_path("images", theme.logo_file())))
        _set_windows_taskbar_identity()

        self.create_custom_title_bar()
        self.load_tabs()

        table = self.conn_table()
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        # Senza questo una connection string lunga manda la riga a capo in mezzo
        # a un percorso: meglio troncarla e lasciarla intera nel tooltip.
        table.setWordWrap(False)

        self.connections = load_connections()
        self.refresh_conn_table()
        self.refresh_comboboxes()
        self.choose_tab.imposta_riepilogo_filtri(self.regole.descrizione())

        self.tabWidget.currentChanged.connect(self.on_tab_changed)
        self._scorciatoie_globali()

        self._ripristina_geometria()
        self._posiziona_presa()
        for riquadro in self.findChildren(Riquadro):
            riquadro.aggiorna_tema()
        self._aggiorna_scanline()
        self._controlla_aggiornamenti_avvio()

    def _scorciatoie_globali(self):
        """Ctrl+1..4 per le schede, F5 per rifare l'ultimo confronto.

        Senza queste, l'unico modo di cambiare scheda da tastiera e' arrivare
        alla barra con Tab e muoversi con le frecce.
        """
        for numero, indice in enumerate(
                (TAB_HOME, TAB_CONFIGURAZIONE, TAB_SCELTA, TAB_RISULTATI), start=1):
            scorciatoia = QtGui.QShortcut(QtGui.QKeySequence(f"Ctrl+{numero}"), self)
            scorciatoia.activated.connect(
                lambda i=indice: self.tabWidget.setCurrentIndex(i))

        aggiorna = QtGui.QShortcut(QtGui.QKeySequence("F5"), self)
        aggiorna.activated.connect(self.start_comparison)

    # --- accesso ai tab ---------------------------------------------------

    def conn_table(self):
        return self.tabWidget.widget(TAB_CONFIGURAZIONE).conn_table

    def scelta_tab(self):
        return self.choose_tab

    # --- gestione connessioni ---------------------------------------------

    def refresh_conn_table(self):
        """Ricostruisce la tabella dal modello in memoria.

        Va rifatta da zero a ogni modifica: i pulsanti riga catturano l'indice,
        che dopo una cancellazione non corrisponderebbe piu' alla riga giusta.
        """
        table = self.conn_table()
        table.setRowCount(0)
        table.setColumnCount(6)
        table.verticalHeader().setVisible(False)   # i numeri di riga non dicono niente
        for column, title in ((COL_NAME, self.tr("Nome")),
                              (COL_STRING, self.tr("Connessione")),
                              (COL_PASSWORD, self.tr("Password")),
                              (COL_SCHEMA, self.tr("Schema")),
                              (COL_EDIT, ""), (COL_DELETE, "")):
            table.setHorizontalHeaderItem(column, QtWidgets.QTableWidgetItem(title))

        for row, connection in enumerate(self.connections):
            table.insertRow(row)
            table.setItem(row, COL_NAME, QtWidgets.QTableWidgetItem(connection.name))

            url = QtWidgets.QTableWidgetItem(mask_password(connection.conn_string))
            url.setToolTip(mask_password(connection.conn_string))
            table.setItem(row, COL_STRING, url)

            table.setCellWidget(row, COL_PASSWORD, self._pastiglia_password(connection))
            table.setItem(row, COL_SCHEMA, QtWidgets.QTableWidgetItem(connection.schema or ""))

            edit_button = QtWidgets.QPushButton()
            edit_button.setIcon(qta.icon("fa5s.pencil-alt", color=_icon_color()))
            edit_button.setToolTip(self.tr("Modifica"))
            edit_button.setAccessibleName(
                self.tr("Modifica la connessione {0}").format(connection.name))
            edit_button.clicked.connect(lambda _=False, r=row: self.edit_connection(r))
            table.setCellWidget(row, COL_EDIT, edit_button)

            delete_button = QtWidgets.QPushButton()
            delete_button.setIcon(qta.icon("fa5s.trash-alt", color=_icon_color()))
            delete_button.setToolTip(self.tr("Elimina"))
            delete_button.setAccessibleName(
                self.tr("Elimina la connessione {0}").format(connection.name))
            delete_button.clicked.connect(lambda _=False, r=row: self.delete_connection(r))
            table.setCellWidget(row, COL_DELETE, delete_button)

        self._sistema_colonne_connessioni(table)

    def _sistema_colonne_connessioni(self, table) -> None:
        """Larghezze della tabella delle connessioni.

        Prima le colonne stavano in ResizeToContents e la stringa in Stretch:
        in entrambe le modalita' Qt non lascia trascinare il bordo, percio'
        questa tabella non si poteva ridimensionare affatto. Ora le colonne
        con del testo sono Interactive, e la stringa di connessione si prende
        lo spazio che avanza al primo riempimento senza perdere la presa.

        Le due colonne dei pulsanti restano aderenti al contenuto: sono icone
        di dimensione fissa, allargarle non servirebbe a niente.
        """
        header = table.horizontalHeader()

        # Come per l'albero dei risultati: anche setSectionResizeMode fa
        # scattare sectionResized, percio' l'interruttore copre tutto.
        self._sto_sistemando_conn = True
        try:
            header.setStretchLastSection(False)
            for column in (COL_EDIT, COL_DELETE):
                header.setSectionResizeMode(
                    column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
            for column in (COL_NAME, COL_STRING, COL_PASSWORD, COL_SCHEMA):
                header.setSectionResizeMode(
                    column, QtWidgets.QHeaderView.ResizeMode.Interactive)

            if self._colonne_conn_sistemate:
                return
            self._colonne_conn_sistemate = True
            header.sectionResized.connect(self._ricorda_colonne_connessioni)

            salvate = preferences.larghezze_colonne(
                NOME_COLONNE_CONNESSIONI, len(LARGHE_CONNESSIONI))
            if salvate:
                # Valgono come pesi: la finestra di oggi non e'
                # necessariamente larga come quella dell'altra volta.
                for column, larghezza in zip(LARGHE_CONNESSIONI, salvate,
                                             strict=False):
                    table.setColumnWidth(column, larghezza)
            else:
                table.resizeColumnsToContents()
            self._proporzioni_conn = self._proporzioni_connessioni(table)
        finally:
            self._sto_sistemando_conn = False

        table.viewport().installEventFilter(self)
        self._distribuisci_colonne_connessioni()

    def _spazio_distribuibile(self, table) -> int:
        """Lo spazio che resta togliendo le colonne dei pulsanti.

        Quelle due stanno aderenti alle icone e non partecipano al riparto:
        allargarle non servirebbe a nulla.
        """
        fissi = sum(table.columnWidth(colonna)
                    for colonna in (COL_EDIT, COL_DELETE))
        return table.viewport().width() - fissi

    def _proporzioni_connessioni(self, table) -> list[float]:
        larghezze = [max(1, table.columnWidth(colonna))
                     for colonna in LARGHE_CONNESSIONI]
        totale = sum(larghezze)
        return [larghezza / totale for larghezza in larghezze]

    def _distribuisci_colonne_connessioni(self) -> None:
        """Riparte fra le colonne lo spazio della finestra.

        Stesso principio dell'albero dei risultati: quello che si imposta a
        mano vale come proporzione, cosi' la tabella continua a riempire la
        finestra quando la si ridimensiona invece di lasciare un vuoto a
        destra.
        """
        if self._proporzioni_conn is None or self._sto_sistemando_conn:
            return
        table = self.conn_table()
        disponibile = self._spazio_distribuibile(table)
        if disponibile <= 0:
            return

        larghezze = [max(MINIMO_COLONNA, round(proporzione * disponibile))
                     for proporzione in self._proporzioni_conn]
        scarto = disponibile - sum(larghezze)
        indice_elastica = LARGHE_CONNESSIONI.index(COL_ELASTICA)
        if scarto > 0:
            larghezze[indice_elastica] += scarto
        elif scarto < 0:
            riducibile = max(0, larghezze[indice_elastica] - MINIMO_COLONNA)
            larghezze[indice_elastica] -= min(-scarto, riducibile)

        self._sto_sistemando_conn = True
        try:
            for colonna, larghezza in zip(LARGHE_CONNESSIONI, larghezze,
                                          strict=False):
                table.setColumnWidth(colonna, larghezza)
        finally:
            self._sto_sistemando_conn = False

    def _riempi_con_elastica(self, table, toccata=None) -> None:
        """Lo spazio liberato da una regolazione va alla stringa di
        connessione, non ridistribuito su tutte: la colonna appena
        trascinata tornerebbe indietro sotto le dita."""
        if toccata is None or toccata == COL_ELASTICA:
            return
        altre = sum(table.columnWidth(colonna) for colonna in LARGHE_CONNESSIONI
                    if colonna != COL_ELASTICA)
        resto = self._spazio_distribuibile(table) - altre
        if resto < MINIMO_COLONNA:
            return
        self._sto_sistemando_conn = True
        try:
            table.setColumnWidth(COL_ELASTICA, resto)
        finally:
            self._sto_sistemando_conn = False

    def _ricorda_colonne_connessioni(self, toccata=None, *_argomenti) -> None:
        """Salva le larghezze scelte trascinando, e solo quelle.

        Come per l'albero dei risultati: Qt emette sectionResized anche
        mentre impagina, prima che le colonne siano state sistemate.
        """
        if self._sto_sistemando_conn or not self._colonne_conn_sistemate:
            return   # le impostiamo noi, o Qt sta ancora impaginando
        tabella = self.conn_table()
        self._riempi_con_elastica(tabella, toccata)
        self._proporzioni_conn = self._proporzioni_connessioni(tabella)
        preferences.imposta_larghezze_colonne(
            NOME_COLONNE_CONNESSIONI,
            [tabella.columnWidth(c) for c in LARGHE_CONNESSIONI])

    def _pastiglia_password(self, connection) -> QtWidgets.QLabel:
        """Dove sta davvero la password di questa connessione.

        E' l'informazione che rende visibile la differenza fra una connessione
        a posto e una con il segreto scritto nel file.
        """
        if usa_portachiavi(connection):
            testo, tipo = self.tr("portachiavi"), "buona"
        elif password_letterale(connection.conn_string):
            testo, tipo = self.tr("in chiaro"), "allarme"
        elif "://" in connection.conn_string and "@" in connection.conn_string:
            testo, tipo = self.tr("variabile"), "neutra"
        else:
            testo, tipo = "—", "neutra"

        etichetta = QtWidgets.QLabel(testo)
        etichetta.setProperty("pastiglia", tipo)
        etichetta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return etichetta

    def persist(self):
        save_connections(self.connections)
        self.refresh_conn_table()
        self.refresh_comboboxes()

    def add_connection(self):
        connection = ask_connection(self)
        if connection is not None:
            self.connections.append(connection)
            self.persist()

    def edit_connection(self, row):
        if not 0 <= row < len(self.connections):
            return
        connection = ask_connection(self, self.connections[row])
        if connection is not None:
            self.connections[row] = connection
            self.persist()

    def delete_connection(self, row):
        if not 0 <= row < len(self.connections):
            return
        name = self.connections[row].name
        confirm = QtWidgets.QMessageBox.question(
            self, self.tr("Elimina connessione"),
            self.tr("Eliminare la connessione '{0}'?").format(name),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
        )
        if confirm == QtWidgets.QMessageBox.StandardButton.Yes:
            del self.connections[row]
            # Via anche la password: una voce orfana nel portachiavi resterebbe
            # li' per sempre, e tornerebbe a galla se qualcuno riusasse il nome.
            if keystore.elimina(name):
                logger.info("Rimossa dal portachiavi la password di '%s'.", name)
            self.persist()

    # --- barra del titolo --------------------------------------------------

    def create_custom_title_bar(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        title_bar = QtWidgets.QWidget(self)
        title_bar.setObjectName("titleBar")
        layout = QtWidgets.QHBoxLayout(title_bar)
        layout.setContentsMargins(0, 0, 0, 0)

        self.logo_label = QtWidgets.QLabel(title_bar)
        self.logo_label.setPixmap(_logo(20))

        self.title_wordmark = WordmarkGradiente("DiFFDB", 15, title_bar)

        # Informazioni e controllo aggiornamenti.
        self.info_button = QtWidgets.QPushButton(title_bar)
        self.info_button.setObjectName("infoButton")
        self.info_button.setToolTip(self.tr("Informazioni e aggiornamenti"))
        self.info_button.setAccessibleName(self.tr("Informazioni"))
        self.info_button.clicked.connect(self._mostra_info)

        # Cambio aspetto: variante (Moderna/Retro) e, nella Moderna, chiaro/scuro.
        self.variant_button = QtWidgets.QPushButton(title_bar)
        self.variant_button.setObjectName("variantButton")
        self.variant_button.setToolTip(self.tr("Cambia aspetto (Moderna / Retro)"))
        self.variant_button.setAccessibleName(self.tr("Cambia aspetto"))
        self.variant_button.clicked.connect(self._cambia_variante)

        self.theme_button = QtWidgets.QPushButton(title_bar)
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setToolTip(self.tr("Tema chiaro / scuro"))
        self.theme_button.setAccessibleName(self.tr("Tema chiaro o scuro"))
        self.theme_button.clicked.connect(self._cambia_tema)

        minimize_button = QtWidgets.QPushButton("_", title_bar)
        minimize_button.setObjectName("minimizeButton")
        minimize_button.setToolTip(self.tr("Riduci a icona"))
        minimize_button.setAccessibleName(self.tr("Riduci a icona"))
        minimize_button.clicked.connect(self.showMinimized)

        self.maximize_button = QtWidgets.QPushButton("□", title_bar)
        self.maximize_button.setObjectName("maximizeButton")
        self.maximize_button.setToolTip(self.tr("Ingrandisci"))
        self.maximize_button.setAccessibleName(self.tr("Ingrandisci"))
        self.maximize_button.clicked.connect(self.toggle_maximized)

        close_button = QtWidgets.QPushButton("X", title_bar)
        close_button.setObjectName("closeButton")
        close_button.setToolTip(self.tr("Chiudi"))
        close_button.setAccessibleName(self.tr("Chiudi la finestra"))
        close_button.clicked.connect(self.close)

        layout.addWidget(self.logo_label)
        layout.addWidget(self.title_wordmark)
        layout.addStretch()
        layout.addWidget(self.info_button)
        layout.addWidget(self.variant_button)
        layout.addWidget(self.theme_button)
        layout.addWidget(minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(close_button)

        self._aggiorna_icone_tema()

        self.setMenuWidget(title_bar)
        # Il trascinamento vale solo sulla barra: prima era attaccato alla finestra
        # intera, e si spostava tutto trascinando un punto vuoto qualsiasi.
        title_bar.mousePressEvent = self._inizia_trascinamento
        title_bar.mouseMoveEvent = self._trascina
        title_bar.mouseDoubleClickEvent = lambda _event: self.toggle_maximized()

        # La presa d'angolo resta come riserva: dove il sistema non supporta
        # startSystemResize, e' l'unico modo di ridimensionare.
        self.size_grip = QtWidgets.QSizeGrip(self)
        self.size_grip.setFixedSize(16, 16)

        # Il filtro per i bordi va sulla finestra di sistema, che pero' puo'
        # non esistere ancora: ci pensa showEvent.
        self._installa_filtro_bordi()

    # --- ridimensionamento dai bordi ---------------------------------------
    #
    # Una finestra senza cornice non ha i bordi di sistema, percio' Qt non la
    # ridimensiona dai lati: c'era solo la presa in basso a destra, e per
    # cambiare larghezza bisognava passare da li'. Qui i bordi tornano
    # sensibili tutti e otto.
    #
    # Il ridimensionamento vero lo fa il sistema operativo
    # (startSystemResize): si ottengono lo snap ai lati dello schermo, il
    # disegno fluido e il comportamento a cui l'utente e' abituato, che
    # rifacendolo a mano spostando la geometria non si avrebbero. La presa
    # d'angolo resta come riserva dove il sistema non lo supporta.

    def _bordi_sotto_il_mouse(self, punto) -> "Qt.Edge":
        """Quali bordi sono sotto il puntatore, se e' abbastanza vicino."""
        bordi = Qt.Edge(0)
        if self.isMaximized() or self.isFullScreen():
            return bordi   # da massimizzata non si ridimensiona
        if punto.x() <= MARGINE_RESIZE:
            bordi |= Qt.Edge.LeftEdge
        elif punto.x() >= self.width() - MARGINE_RESIZE:
            bordi |= Qt.Edge.RightEdge
        if punto.y() <= MARGINE_RESIZE:
            bordi |= Qt.Edge.TopEdge
        elif punto.y() >= self.height() - MARGINE_RESIZE:
            bordi |= Qt.Edge.BottomEdge
        return bordi

    def _forma_cursore(self, bordi):
        """La freccia che dice in che direzione si puo' tirare."""
        return FORME_CURSORE.get(bordi.value)

    def _aggiorna_cursore_bordo(self, bordi) -> None:
        """Tiene un solo cursore sovrapposto per volta.

        Il cursore si sovrascrive a livello di applicazione perche' sotto il
        puntatore, vicino al bordo, c'e' un figlio qualsiasi con il suo
        cursore: impostarlo sulla finestra non si vedrebbe.
        """
        forma = self._forma_cursore(bordi)
        if forma == self._cursore_bordo:
            return
        if self._cursore_bordo is not None:
            QtWidgets.QApplication.restoreOverrideCursor()
        if forma is not None:
            QtWidgets.QApplication.setOverrideCursor(forma)
        self._cursore_bordo = forma

    def _installa_filtro_bordi(self) -> None:
        """Mette il filtro sulla finestra di sistema, non sull'applicazione.

        Due motivi, e il secondo l'ho imparato misurando. La QWindow riceve
        gli eventi del mouse grezzi del sistema prima che Qt li smisti ai
        widget, percio' li vediamo anche quando il puntatore e' sopra un
        figlio vicino al bordo, e senza dover accendere il tracciamento del
        mouse su tutti i figli.

        E soprattutto vede passare solo gli eventi della finestra: con il
        filtro sull'applicazione passava da qui in Python *ogni* evento di
        ogni widget, e applicare un tema - che ne genera a migliaia - era
        diventato quattro volte piu' lento.
        """
        if self._filtro_bordi_attivo:
            return
        maniglia = self.windowHandle()
        if maniglia is None:
            return   # la finestra di sistema non c'e' ancora: si riprova
        maniglia.installEventFilter(self)
        self._filtro_bordi_attivo = True

    def showEvent(self, event):
        super().showEvent(event)
        # windowHandle() esiste solo da quando la finestra e' stata creata.
        self._installa_filtro_bordi()

    def eventFilter(self, oggetto, evento):
        tipo = evento.type()
        if tipo in _EVENTI_MOUSE and oggetto is self.windowHandle():
            # position() e' gia' in coordinate della finestra.
            bordi = self._bordi_sotto_il_mouse(evento.position().toPoint())
            if tipo == QtCore.QEvent.Type.MouseMove:
                self._aggiorna_cursore_bordo(bordi)
            elif bordi and evento.button() == Qt.MouseButton.LeftButton:
                maniglia = self.windowHandle()
                if maniglia is not None and maniglia.startSystemResize(bordi):
                    return True   # da qui lo porta avanti il sistema operativo
        elif tipo == QtCore.QEvent.Type.Leave and oggetto is self.windowHandle():
            self._aggiorna_cursore_bordo(Qt.Edge(0))
        elif tipo == QtCore.QEvent.Type.Resize and self._colonne_conn_sistemate:
            if oggetto is self.conn_table().viewport():
                self._distribuisci_colonne_connessioni()
        return super().eventFilter(oggetto, evento)

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
            self.maximize_button.setText("□")
            self.maximize_button.setToolTip(self.tr("Ingrandisci"))
        else:
            self.showMaximized()
            self.maximize_button.setText("❐")
            self.maximize_button.setToolTip(self.tr("Ripristina"))
        self._posiziona_presa()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._posiziona_presa()
        if getattr(self, "scanline", None) is not None and self.scanline.isVisible():
            self.scanline.setGeometry(self.rect())
            self.scanline.raise_()

    def _posiziona_presa(self):
        if getattr(self, "size_grip", None) is None:
            return
        self.size_grip.move(self.width() - self.size_grip.width(),
                            self.height() - self.size_grip.height())
        self.size_grip.setVisible(not self.isMaximized())
        self.size_grip.raise_()

    def _inizia_trascinamento(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _trascina(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position is not None \
                and not self.isMaximized():
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    # --- tema: variante e chiaro/scuro -------------------------------------

    def _cambia_variante(self):
        nuova = (theme.VARIANTE_RETRO if preferences.variante() == theme.VARIANTE_MODERNA
                 else theme.VARIANTE_MODERNA)
        preferences.imposta_variante(nuova)
        self._applica_tema()

    def _cambia_tema(self):
        # Chiaro/scuro vale per entrambe le varianti: "tutto chiaro" o "tutto scuro".
        nuovo = (theme.TEMA_CHIARO if preferences.tema() == theme.TEMA_SCURO
                 else theme.TEMA_SCURO)
        preferences.imposta_tema(nuovo)
        self._applica_tema()

    def _scegli_colore(self):
        """Apre un selettore e applica subito l'accento scelto."""
        iniziale = QtGui.QColor(preferences.accento())
        colore = QtWidgets.QColorDialog.getColor(
            iniziale, self, self.tr("Colore dell'interfaccia"))
        if colore.isValid():
            preferences.imposta_accento(colore.name().upper())
            self._applica_tema()

    def _ripristina_colore(self):
        preferences.imposta_accento(preferences.ACCENTO_PREDEFINITO)
        self._applica_tema()

    def _applica_tema(self):
        """Riapplica la tavolozza all'applicazione e ricolora cio' che sta nel codice."""
        app = QtWidgets.QApplication.instance()
        theme.applica(app, preferences.variante(), preferences.tema(), preferences.accento())
        self._aggiorna_icone_tema()
        self._recolor_tab_icons()
        self.refresh_conn_table()          # le icone matita/cestino sono colorate a mano
        self.results_tab.aggiorna_tema()   # i colori delle direzioni del diff
        self.home_tab.aggiorna_tema()      # il wordmark a gradiente e il logo
        self.title_wordmark.imposta_tema()
        self.logo_label.setPixmap(_logo(20))                    # pixel nel Retro
        self.setWindowIcon(QtGui.QIcon(resource_path("images", theme.logo_file())))
        for riquadro in self.findChildren(Riquadro):   # titoli TUI e angoli
            riquadro.aggiorna_tema()
        self._aggiorna_scanline()

    def _aggiorna_icone_tema(self):
        self.info_button.setIcon(qta.icon("fa5s.info-circle", color=_icon_color()))
        retro = preferences.variante() == theme.VARIANTE_RETRO
        self.variant_button.setIcon(
            qta.icon("fa5s.desktop" if retro else "fa5s.terminal", color=_icon_color()))
        # Chiaro/scuro vale per entrambe le varianti: il tasto c'e' sempre.
        chiaro = preferences.tema() == theme.TEMA_CHIARO
        self.theme_button.setIcon(
            qta.icon("fa5s.moon" if chiaro else "fa5s.sun", color=_icon_color()))

    def _recolor_tab_icons(self):
        for indice, nome in ((TAB_HOME, "fa5s.home"),
                             (TAB_CONFIGURAZIONE, "fa5s.cog"),
                             (TAB_SCELTA, "fa5s.database"),
                             (TAB_RISULTATI, "fa5s.exchange-alt")):
            self.tabWidget.setTabIcon(indice, qta.icon(nome, color=_icon_color()))

    # --- informazioni e aggiornamenti --------------------------------------

    def _mostra_info(self):
        mostra_info(self)

    def _controlla_aggiornamenti_avvio(self):
        """Controlla gli aggiornamenti all'avvio, ma solo se l'utente l'ha chiesto.

        Spento di default: senza l'opzione, DiFFDB non contatta mai la rete da
        solo (vedi updates.py). In silenzio se fallisce: all'avvio un problema
        di rete non deve disturbare.
        """
        if not preferences.controlla_aggiornamenti_avvio():
            return
        self._upd_thread = QtCore.QThread(self)
        self._upd_worker = UpdateCheckWorker()
        self._upd_worker.moveToThread(self._upd_thread)
        self._upd_thread.started.connect(self._upd_worker.run)
        self._upd_worker.finished.connect(self._aggiornamento_trovato)
        self._upd_worker.failed.connect(lambda _m: self._ferma_upd_thread())
        self._upd_thread.start()

    def _aggiornamento_trovato(self, tag):
        self._ferma_upd_thread()
        if not updates.e_piu_recente(tag):
            return
        risposta = QtWidgets.QMessageBox.question(
            self, self.tr("Aggiornamento disponibile"),
            self.tr("E' disponibile la versione {0}. Aprire la pagina per scaricarla?")
            .format(tag))
        if risposta == QtWidgets.QMessageBox.StandardButton.Yes:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(updates.PAGINA_RELEASE))

    def _ferma_upd_thread(self):
        thread = getattr(self, "_upd_thread", None)
        if thread is not None:
            thread.quit()
            thread.wait()
            self._upd_thread = None
            self._upd_worker = None

    def _aggiorna_scanline(self):
        """Overlay a scanline, solo in variante Retro."""
        retro = preferences.variante() == theme.VARIANTE_RETRO
        if retro and getattr(self, "scanline", None) is None:
            self.scanline = _Scanline(self)
        if getattr(self, "scanline", None) is not None:
            self.scanline.setVisible(retro)
            if retro:
                self.scanline.setGeometry(self.rect())
                self.scanline.raise_()

    def _ripristina_geometria(self):
        salvata = preferences.geometria()
        if salvata is None:
            return
        self.resize(salvata["larghezza"], salvata["altezza"])
        self.move(salvata["x"], salvata["y"])
        if salvata["massimizzata"]:
            self.toggle_maximized()

    def closeEvent(self, event):
        # Il cursore sovrapposto e' globale: lasciandolo impostato, la freccia
        # di ridimensionamento resterebbe anche sulle altre finestre.
        self._aggiorna_cursore_bordo(Qt.Edge(0))
        maniglia = self.windowHandle()
        if maniglia is not None and self._filtro_bordi_attivo:
            maniglia.removeEventFilter(self)
            self._filtro_bordi_attivo = False

        # Da massimizzata si salva la dimensione normale: al riavvio si torna
        # massimizzati, e chi ripristina ritrova la finestra di prima.
        normale = self.normalGeometry() if self.isMaximized() else self.geometry()
        preferences.imposta_geometria(
            normale.width(), normale.height(), normale.x(), normale.y(), self.isMaximized())
        super().closeEvent(event)

    # --- tab ---------------------------------------------------------------

    def load_tabs(self):
        tab_config = load_ui(resource_path("ui", "configurazione.ui"))

        self.home_tab = HomeTab()
        self.choose_tab = ChooseTab()
        self.results_tab = ResultsTab(
            on_export_excel=self.export_excel, on_export_sql=self.export_sql,
            on_accept=self.accetta_differenze)

        self.tabWidget.insertTab(TAB_HOME, self.home_tab,
                                 qta.icon("fa5s.home", color=_icon_color()), self.tr("Home"))
        self.tabWidget.insertTab(TAB_CONFIGURAZIONE, tab_config,
                                 qta.icon("fa5s.cog", color=_icon_color()),
                                 self.tr("Configurazione"))
        self.tabWidget.insertTab(TAB_SCELTA, self.choose_tab,
                                 qta.icon("fa5s.database", color=_icon_color()), self.tr("Scelta"))
        self.tabWidget.insertTab(TAB_RISULTATI, self.results_tab,
                                 qta.icon("fa5s.exchange-alt", color=_icon_color()),
                                 self.tr("Risultati"))

        self.home_tab.vai_al_confronto.connect(
            lambda: self.tabWidget.setCurrentIndex(TAB_SCELTA))
        self.home_tab.vai_alle_connessioni.connect(
            lambda: self.tabWidget.setCurrentIndex(TAB_CONFIGURAZIONE))
        self.home_tab.ripeti_confronto.connect(self.ripeti_confronto)

        self.choose_tab.confronta.connect(self.start_comparison)
        self.choose_tab.annulla_operazione.connect(self.annulla_operazione)
        self.choose_tab.salva_snapshot.connect(self.save_snapshot)
        self.choose_tab.confronta_con_file.connect(self.compare_with_snapshot_file)
        self.choose_tab.riprova.connect(self.start_comparison)
        self.choose_tab.modifica_connessione.connect(self._modifica_db2)
        self.choose_tab.modifica_filtri.connect(self.modifica_filtri)

        self._sistema_intestazione_connessioni(tab_config)
        self._aggiungi_preferenze(tab_config)
        tab_config.add_conn_button.clicked.connect(self.add_connection)

    def _sistema_intestazione_connessioni(self, tab_config):
        """Titolo a sinistra e pulsante a destra, al posto di un pulsante largo
        quanto la finestra che dominava la schermata."""
        layout = tab_config.layout()
        pulsante = tab_config.add_conn_button
        if layout is None:
            return

        layout.removeWidget(pulsante)
        pulsante.setText(self.tr("Aggiungi connessione"))
        pulsante.setIcon(qta.icon("fa5s.plus", color=_icon_color()))
        pulsante.setSizePolicy(QtWidgets.QSizePolicy.Policy.Maximum,
                               QtWidgets.QSizePolicy.Policy.Fixed)

        titolo = QtWidgets.QLabel(self.tr("Connessioni"), tab_config)
        titolo.setProperty("ruolo", "titolo")

        riga = QtWidgets.QHBoxLayout()
        riga.addWidget(titolo)
        riga.addStretch()
        riga.addWidget(pulsante)
        layout.insertLayout(0, riga)

    def _aggiungi_preferenze(self, tab_config):
        """Sezione preferenze, separata dall'elenco delle connessioni.

        Cambiare lingua richiede un riavvio: i testi dei widget si fissano quando
        i widget vengono creati, e ricostruire tutta la finestra a caldo
        costerebbe molto piu' di quanto valga.
        """
        layout = tab_config.layout()
        if layout is None:
            return

        separatore = QtWidgets.QFrame(tab_config)
        separatore.setProperty("ruolo", "separatore")
        separatore.setFixedHeight(1)

        intestazione = QtWidgets.QLabel(self.tr("Preferenze"), tab_config)
        intestazione.setProperty("ruolo", "didascalia")

        riga = QtWidgets.QHBoxLayout()
        riga.addWidget(QtWidgets.QLabel(self.tr("Lingua:"), tab_config))

        self.language_combo = QtWidgets.QComboBox(tab_config)
        for codice, nome in i18n.lingue_disponibili().items():
            self.language_combo.addItem(nome, codice)
        indice = self.language_combo.findData(preferences.lingua())
        if indice >= 0:
            self.language_combo.setCurrentIndex(indice)
        self.language_combo.currentIndexChanged.connect(self._cambia_lingua)

        riga.addWidget(self.language_combo)
        riga.addSpacing(24)

        # Colore dell'interfaccia: alcuni preset piu' un selettore libero.
        riga.addWidget(QtWidgets.QLabel(self.tr("Colore:"), tab_config))
        for colore in ("#6FA888", "#49B0A0", "#3FB6C9", "#5C86C8",
                       "#B07CD8", "#D06AA8", "#C96A6A", "#C9A227"):
            riga.addWidget(self._pastiglia_preset(colore, tab_config))

        self.pulsante_colore = QtWidgets.QPushButton(self.tr("Personalizza..."), tab_config)
        self.pulsante_colore.clicked.connect(self._scegli_colore)
        riga.addWidget(self.pulsante_colore)

        ripristina = QtWidgets.QPushButton(tab_config)
        ripristina.setIcon(qta.icon("fa5s.undo", color=_icon_color()))
        ripristina.setToolTip(self.tr("Ripristina il colore predefinito"))
        ripristina.clicked.connect(self._ripristina_colore)
        riga.addWidget(ripristina)
        riga.addStretch()

        layout.addWidget(separatore)
        layout.addWidget(intestazione)
        layout.addLayout(riga)

    def _pastiglia_preset(self, colore: str, parent) -> QtWidgets.QPushButton:
        """Quadratino cliccabile che imposta un accento predefinito."""
        pulsante = QtWidgets.QPushButton(parent)
        pulsante.setFixedSize(22, 22)
        pulsante.setCursor(Qt.CursorShape.PointingHandCursor)
        pulsante.setToolTip(colore)
        pulsante.setStyleSheet(
            f"background-color: {colore}; border: 1px solid rgba(0,0,0,60);"
            f" border-radius: 4px;")
        pulsante.clicked.connect(lambda _=False, c=colore: self._imposta_colore(c))
        return pulsante

    def _imposta_colore(self, colore: str):
        preferences.imposta_accento(colore)
        self._applica_tema()

    def _cambia_lingua(self):
        codice = self.language_combo.currentData()
        if codice == preferences.lingua():
            return
        preferences.imposta_lingua(codice)
        QtWidgets.QMessageBox.information(
            self, self.tr("Lingua"),
            self.tr("La nuova lingua sara' attiva al prossimo avvio di DiFFDB."))

    def refresh_comboboxes(self):
        self.choose_tab.imposta_connessioni(self.connections)
        self.home_tab.aggiorna(self.connections, preferences.ultimo_confronto())

    def selected_connections(self):
        return self.choose_tab.selezionate()

    def ripeti_confronto(self, riferimento: str, da_allineare: str):
        """Riesegue l'ultimo confronto dalla schermata iniziale."""
        for combo, nome in ((self.choose_tab.comboBox1, riferimento),
                            (self.choose_tab.comboBox2, da_allineare)):
            indice = combo.findData(nome)
            if indice < 0:
                QtWidgets.QMessageBox.warning(
                    self, self.tr("Ambiente non trovato"),
                    self.tr("La connessione '{0}' non esiste piu'.").format(nome))
                self.tabWidget.setCurrentIndex(TAB_SCELTA)
                return
            combo.setCurrentIndex(indice)

        self.tabWidget.setCurrentIndex(TAB_SCELTA)
        self.start_comparison()

    def on_tab_changed(self, index):
        if index in (TAB_HOME, TAB_SCELTA):
            self.refresh_comboboxes()

    # --- confronto ---------------------------------------------------------

    def start_comparison(self):
        conn1, conn2 = self.selected_connections()
        if conn1 is None or conn2 is None:
            QtWidgets.QMessageBox.warning(
                self, self.tr("Connessioni mancanti"),
                self.tr("Configura almeno due connessioni nella scheda Configurazione."))
            return
        if conn1.name == conn2.name:
            QtWidgets.QMessageBox.warning(
                self, self.tr("Ambienti uguali"),
                self.tr("Seleziona due ambienti diversi da confrontare."))
            return

        self.choose_tab.mostra_avanzamento(self.tr("Confronto in corso..."))
        self._run(CompareWorker(conn1, conn2, self.regole), self.on_comparison_done)

    def compare_with_snapshot_file(self):
        """Confronta il primo ambiente selezionato con uno snapshot salvato."""
        conn1, _ = self.selected_connections()
        if conn1 is None:
            QtWidgets.QMessageBox.warning(
                self, self.tr("Nessun ambiente"),
                self.tr("Seleziona l'ambiente da confrontare con lo snapshot."))
            return

        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, self.tr("Snapshot da confrontare"), self.output_dir,
            self.tr("Snapshot DiFFDB (*.json)"))
        if not path:
            return

        try:
            baseline = SnapshotFile.at(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Snapshot illeggibile"), str(exc))
            return

        # La baseline sta a sinistra: si legge "cosa e' cambiato da allora a oggi".
        self.choose_tab.mostra_avanzamento(self.tr("Confronto con lo snapshot in corso..."))
        self._run(CompareWorker(baseline, conn1, self.regole), self.on_comparison_done)

    def save_snapshot(self):
        """Salva su file la struttura del primo ambiente selezionato."""
        conn1, _ = self.selected_connections()
        if conn1 is None:
            QtWidgets.QMessageBox.warning(
                self, self.tr("Nessun ambiente"),
                self.tr("Seleziona l'ambiente di cui salvare lo snapshot."))
            return

        suggested = str(config_dir() / f"snapshot_{slug(conn1.name)}.json")
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, self.tr("Dove salvare lo snapshot"), suggested,
            self.tr("Snapshot DiFFDB (*.json)"))
        if not path:
            return

        self.choose_tab.mostra_avanzamento(
            self.tr("Lettura della struttura di {0}...").format(conn1.name))
        self._run(SnapshotWorker(conn1, path, self.regole), self.on_snapshot_saved)

    def on_comparison_done(self, diff):
        self.cleanup_thread()
        self.choose_tab.mostra_scelta()
        # Serve per ricalcolare in memoria dopo aver accettato delle differenze,
        # senza rileggere i due ambienti dal vivo.
        self._ultimo_diff = diff

        # Annotato per la schermata iniziale: e' la prima cosa che si cerca
        # riaprendo l'applicazione.
        preferences.imposta_ultimo_confronto(
            diff.snapshot1.env_name, diff.snapshot2.env_name, len(diff.all),
            QtCore.QDateTime.currentDateTimeUtc().toString(QtCore.Qt.DateFormat.ISODate))

        # I risultati vanno nel tab: l'utente li rivede e decide cosa esportare.
        self.results_tab.show_result(diff)
        self.tabWidget.setCurrentIndex(TAB_RISULTATI)

        if diff.is_empty:
            self.choose_tab.imposta_stato(self.tr("Nessuna differenza trovata."))
        else:
            self.choose_tab.imposta_stato(
                self.tr("{0} differenze trovate.").format(len(diff.all)))

    def on_snapshot_saved(self, path):
        self.cleanup_thread()
        self.choose_tab.mostra_scelta()
        self.choose_tab.imposta_stato(self.tr("Snapshot salvato."))
        QtWidgets.QMessageBox.information(
            self, self.tr("Snapshot salvato"), self.tr("Salvato in:\n{0}").format(path))

    def on_comparison_failed(self, message):
        self.cleanup_thread()
        # I driver mettono l'URL completo nei messaggi d'errore: va mascherato
        # prima di finire in una schermata che l'utente fotografa e allega a un ticket.
        self.choose_tab.mostra_errore(sanitize(message))
        self.tabWidget.setCurrentIndex(TAB_SCELTA)

    def modifica_filtri(self):
        """Apre l'editor dei filtri e, se si salva, li scrive accanto alla config.

        Il file e' lo stesso che leggono CLI e CI: cosi' un filtro impostato dalla
        GUI vale anche in pipeline, e resta versionabile con il resto.
        """
        nuove = _chiedi_filtri(self, self.regole)
        if nuove is None:
            return
        percorso = config_dir() / NOME_PREDEFINITO
        try:
            salva(nuove, percorso)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Filtri"),
                self.tr("Impossibile salvare i filtri in {0}: {1}").format(percorso, exc))
            return
        self.regole = nuove
        self.choose_tab.imposta_riepilogo_filtri(self.regole.descrizione())
        self.choose_tab.imposta_stato(
            self.tr("Filtri aggiornati: il prossimo confronto li applica."))

    def accetta_differenze(self, differenze):
        """Aggiunge le differenze scelte alle 'accettate' e le nasconde.

        E' la baseline tipo-linter: da qui in poi il confronto resta verde
        finche' una di queste non cambia. Scrive nello stesso diffdb.rules.json
        che leggono CLI e CI, cosi' la decisione vale anche in pipeline.
        """
        if not differenze or self._ultimo_diff is None:
            return

        percorso = config_dir() / NOME_PREDEFINITO
        conferma = QtWidgets.QMessageBox.question(
            self, self.tr("Accetta differenze"),
            self.tr("Segnare {0} differenze come note e volute?\n\n"
                    "Non verranno piu' mostrate nei prossimi confronti, finche' non "
                    "cambiano. La scelta viene salvata in:\n{1}").format(
                        len(differenze), percorso))
        if conferma != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        # Non si muta regole.accettate sul posto: NESSUNA e' un singleton
        # condiviso da tutto il processo (vedi la CLI).
        nuove_chiavi = {chiave(d) for d in differenze}
        aggiornata = dataclasses.replace(
            self.regole, accettate=self.regole.accettate | nuove_chiavi)
        try:
            salva(aggiornata, percorso)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Accetta differenze"),
                self.tr("Impossibile salvare in {0}: {1}").format(percorso, exc))
            return

        self.regole = aggiornata
        # Ricalcola dallo stesso snapshot: le accettate spariscono, senza
        # ricollegarsi ai database.
        nuovo = compare_snapshots(
            self._ultimo_diff.snapshot1, self._ultimo_diff.snapshot2, self.regole)
        self._ultimo_diff = nuovo
        self.results_tab.show_result(nuovo)
        self.choose_tab.imposta_riepilogo_filtri(self.regole.descrizione())
        self.choose_tab.imposta_stato(
            self.tr("{0} differenze accettate: non verranno piu' mostrate.").format(
                len(differenze)))

    def _run(self, worker, on_finished):
        """Manda un worker su un thread suo. Uno alla volta: la GUI ne mostra uno solo."""
        if self.thread is not None:
            return
        self._set_busy(True)

        self.thread = QtCore.QThread(self)
        self.worker = worker
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.progress.connect(self.choose_tab.avanza)
        worker.finished.connect(on_finished)
        worker.failed.connect(self.on_comparison_failed)
        if hasattr(worker, "annullato"):
            worker.annullato.connect(self.on_annullato)
        self.thread.start()

    def annulla_operazione(self):
        """Chiude le connessioni in corso: la lettura fallisce e il thread esce."""
        if self.worker is not None and hasattr(self.worker, "annulla"):
            self.choose_tab.imposta_stato(self.tr("Annullamento in corso..."))
            self.worker.annulla()

    def on_annullato(self):
        self.cleanup_thread()
        self.choose_tab.mostra_scelta()
        self.choose_tab.imposta_stato(self.tr("Operazione annullata."))

    def _modifica_db2(self):
        """Apre la connessione da allineare in modifica, dalla schermata d'errore."""
        _, conn2 = self.selected_connections()
        if conn2 is None:
            return
        for riga, connessione in enumerate(self.connections):
            if connessione.name == conn2.name:
                self.choose_tab.mostra_scelta()
                self.tabWidget.setCurrentIndex(TAB_CONFIGURAZIONE)
                self.edit_connection(riga)
                return

    def _set_busy(self, busy: bool):
        self.choose_tab.imposta_occupato(busy)

    # --- export (richiamati dal tab dei risultati) -------------------------

    def _ask_output_dir(self) -> str:
        return QtWidgets.QFileDialog.getExistingDirectory(
            self, self.tr("Dove salvare i file"), self.output_dir)

    def export_excel(self, diff):
        output_dir = self._ask_output_dir()
        if not output_dir:
            return
        self.output_dir = output_dir
        preferences.imposta_cartella_output(output_dir)
        try:
            path = write_excel(diff, output_dir)
        except Exception as exc:
            logger.exception("Scrittura Excel fallita")
            QtWidgets.QMessageBox.critical(
                self, self.tr("Errore"),
                self.tr("Impossibile scrivere il file: {0}").format(exc))
            return
        QtWidgets.QMessageBox.information(
            self, self.tr("Excel esportato"), self.tr("Salvato in:\n{0}").format(path))

    def export_sql(self, diff, totali=None):
        output_dir = self._ask_output_dir()
        if not output_dir:
            return
        self.output_dir = output_dir
        preferences.imposta_cartella_output(output_dir)
        try:
            written = write_sql(diff, output_dir, totali=totali)
        except Exception as exc:
            logger.exception("Scrittura SQL fallita")
            QtWidgets.QMessageBox.critical(
                self, self.tr("Errore"),
                self.tr("Impossibile scrivere i file: {0}").format(exc))
            return
        if not written:
            QtWidgets.QMessageBox.information(
                self, self.tr("Niente da generare"),
                self.tr("Le differenze selezionate non producono script (es. solo avvisi)."))
            return
        QtWidgets.QMessageBox.information(
            self, self.tr("SQL esportato"),
            self.tr("File generati:\n{0}").format("\n".join(written)))

    def cleanup_thread(self):
        self._set_busy(False)
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
            self.worker = None


def _carica_regole():
    """Regole trovate accanto alla configurazione, se ce ne sono.

    Un file rotto non deve impedire l'avvio: si parte senza filtri e lo si
    scrive nel log.
    """
    percorso = cerca([config_dir()])
    if percorso is None:
        return NESSUNA
    try:
        regole = carica(percorso)
    except RegoleNonValide as exc:
        logger.warning("Regole ignorate: %s", exc)
        return NESSUNA
    logger.info("Regole da '%s': %s", percorso, regole.descrizione() or "nessun filtro")
    return regole


class _Scanline(QtWidgets.QWidget):
    """Righe orizzontali tenui sopra tutta la finestra: l'atmosfera da terminale
    della variante Retro. Trasparente al mouse, non intercetta i clic."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0, 38))
        for y in range(0, self.height(), 3):
            painter.drawRect(0, y, self.width(), 1)


def _logo(size: int) -> QtGui.QPixmap:
    # Disegnato col gradiente del tema: segue variante (geom/pixel) e colore.
    return logo_pixmap(size)


def _set_windows_taskbar_identity():
    """Icona corretta nella taskbar di Windows. Su Linux e macOS non serve."""
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("diffdb.app.1.0")
    except Exception as exc:  # pragma: no cover - dipende dalla versione di Windows
        logger.debug("AppUserModelID non impostato: %s", exc)
