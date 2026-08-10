import streamlit as st
import pandas as pd
import json
import os
import sqlite3
from datetime import datetime
import io
import hashlib

# ReportLab para generación de PDFs
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

# ==========================================
# 1. CONFIGURACIÓN Y BASE DE DATOS CENTRALIZADA
# ==========================================

CARPETA_DATOS = "datos"
DB_HISTORIAL = os.path.join(CARPETA_DATOS, "sistema.db")

def hash_password(password: str) -> str:
    """Encripta la contraseña usando SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def obtener_conexion():
    """Crea la carpeta de datos si no existe y retorna la conexión a SQLite."""
    if not os.path.exists(CARPETA_DATOS):
        os.makedirs(CARPETA_DATOS)
    return sqlite3.connect(DB_HISTORIAL)

def inicializar_db_segura():
    """Crea las tablas de historial, usuarios e inventario en SQLite dentro de la carpeta 'datos'."""
    conn = obtener_conexion()
    cursor = conn.cursor()
    
    # Tabla de historial de cotizaciones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historial (
            id_cotizacion TEXT PRIMARY KEY,
            usuario TEXT NOT NULL,
            fecha TEXT NOT NULL,
            cliente TEXT NOT NULL,
            total REAL NOT NULL,
            productos_json TEXT NOT NULL
        )
    ''')
    
    # Tabla de usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            usuario TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            es_maestro INTEGER NOT NULL
        )
    ''')

    # Tabla de inventario centralizada (reemplaza los archivos Excel)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventario (
            id TEXT NOT NULL,
            usuario TEXT NOT NULL,
            producto TEXT NOT NULL,
            precio_base REAL NOT NULL,
            precio_venta REAL NOT NULL,
            stock INTEGER NOT NULL,
            comentarios TEXT,
            PRIMARY KEY (id, usuario)
        )
    ''')
    
    # Crear usuario maestro por defecto si la tabla de usuarios está vacía
    cursor.execute('SELECT COUNT(*) FROM usuarios')
    if cursor.fetchone()[0] == 0:
        pw_encriptada = hash_password("admin123")
        cursor.execute('INSERT INTO usuarios (usuario, password, es_maestro) VALUES (?, ?, ?)', 
                       ("admin", pw_encriptada, 1))
        
    conn.commit()
    conn.close()

# ==========================================
# 2. GESTIÓN DE INVENTARIO EN SQLITE
# ==========================================

def cargar_inventario_usuario(usuario: str) -> pd.DataFrame:
    """Carga el inventario del usuario desde SQLite. Si está vacío, registra productos demo."""
    conn = obtener_conexion()
    query = """
        SELECT id AS ID, producto AS PRODUCTO, precio_base AS PRECIO_BASE, 
               precio_venta AS PRECIO_VENTA, stock AS STOCK, comentarios AS COMENTARIOS 
        FROM inventario WHERE usuario = ?
    """
    df = pd.read_sql_query(query, conn, params=(usuario,))
    
    if df.empty:
        # Insertar productos iniciales de demostración en SQLite si no existen registros para el usuario
        df_base = pd.DataFrame({
            "ID": ["P-1", "P-2"],
            "usuario": [usuario, usuario],
            "PRODUCTO": ["Producto Demo 1", "Producto Demo 2"],
            "PRECIO_BASE": [50.0, 100.0],
            "PRECIO_VENTA": [80.0, 150.0],
            "STOCK": [20, 15],
            "COMENTARIOS": ["Stock inicial", "Stock inicial"]
        })
        cursor = conn.cursor()
        for _, row in df_base.iterrows():
            cursor.execute('''
                INSERT OR REPLACE INTO inventario (id, usuario, producto, precio_base, precio_venta, stock, comentarios)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (row["ID"], usuario, row["PRODUCTO"], row["PRECIO_BASE"], row["PRECIO_VENTA"], row["STOCK"], row["COMENTARIOS"]))
        conn.commit()
        
        # Volver a leer la tabla con los datos insertados
        df = pd.read_sql_query(query, conn, params=(usuario,))
    
    conn.close()
    return df

def agregar_producto_usuario(usuario: str, id_prod: str, nombre: str, p_base: float, p_venta: float, stock: int, comentarios: str):
    """Guarda o actualiza un producto en la tabla de inventario en SQLite."""
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO inventario (id, usuario, producto, precio_base, precio_venta, stock, comentarios)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (id_prod, usuario, nombre, p_base, p_venta, stock, comentarios))
    conn.commit()
    conn.close()

def actualizar_stock_usuario(usuario: str, id_prod: str, cantidad_descontar: int):
    """Descuenta la cantidad vendida del stock de un producto."""
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE inventario 
        SET stock = stock - ? 
        WHERE id = ? AND usuario = ?
    ''', (cantidad_descontar, id_prod, usuario))
    conn.commit()
    conn.close()

def devolver_stock_usuario(usuario: str, id_prod: str, cantidad_reponer: int):
    """Devuelve la cantidad al stock cuando una cotización es eliminada."""
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE inventario 
        SET stock = stock + ? 
        WHERE id = ? AND usuario = ?
    ''', (cantidad_reponer, id_prod, usuario))
    conn.commit()
    conn.close()

def obtener_siguiente_id(df_inventario: pd.DataFrame) -> str:
    """Calcula el siguiente código autogenerado 'P-X'."""
    if df_inventario.empty or 'ID' not in df_inventario.columns:
        return "P-1"
    numeros = []
    for item in df_inventario['ID']:
        item_str = str(item)
        if item_str.startswith("P-"):
            try:
                numeros.append(int(item_str.split("-")[1]))
            except ValueError:
                pass
    siguiente = max(numeros) + 1 if numeros else 1
    return f"P-{siguiente}"

# ==========================================
# 3. GESTIÓN DE HISTORIAL Y COTIZACIONES
# ==========================================

def guardar_cotizacion_bd(usuario: str, cliente: str, total: float, productos: list) -> str:
    conn = obtener_conexion()
    cursor = conn.cursor()
    fecha_str = datetime.now().strftime("%Y%m%d%H%M%S")
    id_cot = f"COT-{fecha_str}"
    fecha_format = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute('''
        INSERT INTO historial (id_cotizacion, usuario, fecha, cliente, total, productos_json)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (id_cot, usuario, fecha_format, cliente, total, json.dumps(productos)))
    conn.commit()
    conn.close()
    return id_cot

def obtener_historial_usuario(usuario: str) -> list:
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT id_cotizacion, fecha, cliente, total, productos_json FROM historial WHERE usuario = ? ORDER BY fecha DESC', (usuario,))
    registros = cursor.fetchall()
    conn.close()
    resultado = []
    for reg in registros:
        resultado.append({
            "id_cotizacion": reg[0],
            "fecha": reg[1],
            "cliente": reg[2],
            "total": reg[3],
            "productos": json.loads(reg[4])
        })
    return resultado

def eliminar_cotizacion_y_devolver_stock(id_cotizacion: str, usuario: str) -> bool:
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT productos_json FROM historial WHERE id_cotizacion = ? AND usuario = ?', (id_cotizacion, usuario))
    row = cursor.fetchone()
    if row:
        productos = json.loads(row[0])
        for prod in productos:
            devolver_stock_usuario(usuario, prod["id"], prod["cantidad"])
        cursor.execute('DELETE FROM historial WHERE id_cotizacion = ? AND usuario = ?', (id_cotizacion, usuario))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

# ==========================================
# 4. FUNCIONES DE AUTENTICACIÓN
# ==========================================

def verificar_usuario(usuario: str, password: str) -> dict:
    """Verifica si el usuario y contraseña coinciden en la base de datos."""
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT es_maestro FROM usuarios WHERE usuario = ? AND password = ?', (usuario, hash_password(password)))
    row = cursor.fetchone()
    conn.close()
    if row is not None:
        return {"valido": True, "es_maestro": bool(row[0])}
    return {"valido": False, "es_maestro": False}

def crear_nuevo_usuario(nuevo_usuario: str, password: str) -> bool:
    """Guarda un nuevo usuario regular en la base de datos."""
    conn = obtener_conexion()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO usuarios (usuario, password, es_maestro) VALUES (?, ?, ?)', 
                       (nuevo_usuario, hash_password(password), 0))
        conn.commit()
        exito = True
    except sqlite3.IntegrityError:
        exito = False
    finally:
        conn.close()
    return exito

# ==========================================
# 5. GENERACIÓN DE PDF PÁGINA POR PÁGINA
# ==========================================

def generar_pdf_general_paginado(historial: list, usuario: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elementos = []
    estilos = getSampleStyleSheet()
    for idx, cot in enumerate(historial):
        elementos.append(Paragraph(f"<b>REPORTE DE COTIZACIÓN</b>", estilos['Title']))
        elementos.append(Paragraph(f"<b>ID Cotización:</b> {cot['id_cotizacion']} | <b>Usuario:</b> {usuario}", estilos['Normal']))
        elementos.append(Paragraph(f"<b>Cliente:</b> {cot['cliente']} | <b>Fecha:</b> {cot['fecha']}", estilos['Normal']))
        elementos.append(Spacer(1, 15))
        datos_tabla = [["ID", "Producto", "Cant.", "P. Unitario", "Subtotal"]]
        for p in cot['productos']:
            datos_tabla.append([
                str(p['id']), str(p['nombre']), str(p['cantidad']),
                f"${p['precio']:.2f}", f"${(p['cantidad'] * p['precio']):.2f}"
            ])
        datos_tabla.append(["", "", "", "TOTAL:", f"${cot['total']:.2f}"])
        tabla = Table(datos_tabla, colWidths=[60, 220, 50, 80, 80])
        tabla.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTNAME', (3, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (3, -1), (-1, -1), colors.HexColor("#ECF0F1")),
        ]))
        elementos.append(tabla)
        if idx < len(historial) - 1:
            elementos.append(PageBreak())
    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()

# ==========================================
# 6. INTERFAZ EN STREAMLIT
# ==========================================

inicializar_db_segura()
st.set_page_config(page_title="Sistema de Cotizaciones", layout="wide")

# --- CONTROL DE SESIÓN ---
if 'usuario_activo' not in st.session_state:
    st.session_state.usuario_activo = None
    st.session_state.es_maestro = False

if st.session_state.usuario_activo is None:
    # Pantalla de Login
    st.title("🔐 Iniciar Sesión")
    with st.form("login_form"):
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Ingresar")
        
        if submit:
            resultado = verificar_usuario(username, password)
            if resultado["valido"]:
                st.session_state.usuario_activo = username
                st.session_state.es_maestro = resultado["es_maestro"]
                st.success("Acceso concedido. Cargando...")
                st.rerun()
            else:
                st.error("Usuario o contraseña incorrectos.")
else:
    # Botón para cerrar sesión
    st.sidebar.title(f"👤 Bienvenido, {st.session_state.usuario_activo}")
    if st.sidebar.button("Cerrar Sesión"):
        st.session_state.usuario_activo = None
        st.session_state.es_maestro = False
        st.rerun()

    usuario_activo = st.session_state.usuario_activo
    df_inventario = cargar_inventario_usuario(usuario_activo)

    # --- CONFIGURACIÓN DE PESTAÑAS SEGÚN ROL ---
    if st.session_state.es_maestro:
        tabs = st.tabs(["📄 Nueva Cotización", "⚙️ Gestión de Inventario", "📊 Historial de Cotizaciones", "👥 Gestión de Usuarios"])
    else:
        tabs = st.tabs(["📄 Nueva Cotización", "⚙️ Gestión de Inventario", "📊 Historial de Cotizaciones"])

    # --- PESTAÑA 1: NUEVA COTIZACIÓN ---
    with tabs[0]:
        st.header("Crear Cotización")
        cliente = st.text_input("Nombre del Cliente:")
        
        st.subheader("Seleccionar Productos")
        prod_sel = st.selectbox("Producto:", df_inventario["PRODUCTO"].tolist() if not df_inventario.empty else [])
        cant_sel = st.number_input("Cantidad:", min_value=1, value=1)
        
        if "carrito" not in st.session_state:
            st.session_state.carrito = []
            
        if st.button("➕ Agregar al Carrito"):
            if prod_sel:
                row = df_inventario[df_inventario["PRODUCTO"] == prod_sel].iloc[0]
                if cant_sel <= row["STOCK"]:
                    st.session_state.carrito.append({
                        "id": row["ID"], "nombre": row["PRODUCTO"], "precio": float(row["PRECIO_VENTA"]), "cantidad": int(cant_sel)
                    })
                    st.success("Producto agregado.")
                else:
                    st.error("Stock insuficiente.")

        if st.session_state.carrito:
            df_cart = pd.DataFrame(st.session_state.carrito)
            df_cart["Subtotal"] = df_cart["precio"] * df_cart["cantidad"]
            st.dataframe(df_cart, use_container_width=True)
            total = df_cart["Subtotal"].sum()
            st.write(f"### Total: ${total:,.2f}")
            
            if st.button("💾 Finalizar y Guardar Cotización"):
                if cliente:
                    for item in st.session_state.carrito:
                        actualizar_stock_usuario(usuario_activo, item["id"], item["cantidad"])
                    id_generado = guardar_cotizacion_bd(usuario_activo, cliente, total, st.session_state.carrito)
                    st.session_state.carrito = []
                    st.success(f"Cotización {id_generado} guardada.")
                    st.rerun()
                else:
                    st.warning("Ingresa el nombre del cliente.")

    # --- PESTAÑA 2: INVENTARIO ---
    with tabs[1]:
        st.header("Inventario de Productos")
        st.dataframe(df_inventario, use_container_width=True)
        st.subheader("Añadir Nuevo Producto")
        siguiente_id = obtener_siguiente_id(df_inventario)
        st.text_input("ID de Producto (Autogenerado):", value=siguiente_id, disabled=True)
        nuevo_nombre = st.text_input("Nombre del Producto:")
        col_a, col_b, col_c = st.columns(3)
        p_base = col_a.number_input("Precio Base:", min_value=0.0, value=10.0)
        p_venta = col_b.number_input("Precio Venta:", min_value=0.0, value=15.0)
        stock_i = col_c.number_input("Stock Inicial:", min_value=0, value=10)
        comentarios = st.text_input("Comentarios:")
        if st.button("💾 Guardar Producto"):
            if nuevo_nombre:
                agregar_producto_usuario(usuario_activo, siguiente_id, nuevo_nombre, p_base, p_venta, stock_i, comentarios)
                st.success("Producto registrado en la base de datos.")
                st.rerun()
            else:
                st.warning("Por favor, ingresa el nombre del producto.")

    # --- PESTAÑA 3: HISTORIAL ---
    with tabs[2]:
        st.header("Historial de Cotizaciones")
        historial = obtener_historial_usuario(usuario_activo)
        if historial:
            pdf_bytes = generar_pdf_general_paginado(historial, usuario_activo)
            st.download_button(
                label="📄 Descargar Reporte (PDF Paginado)", data=pdf_bytes,
                file_name=f"Reporte_Cotizaciones_{usuario_activo}.pdf", mime="application/pdf"
            )
            st.divider()
            for cot in historial:
                c1, c2 = st.columns([4, 1])
                with c1:
                    st.markdown(f"**ID:** `{cot['id_cotizacion']}` | **Cliente:** {cot['cliente']} | **Fecha:** {cot['fecha']} | **Total:** `${cot['total']:,.2f}`")
                with c2:
                    if st.button("🗑️ Eliminar", key=f"del_{cot['id_cotizacion']}"):
                        if eliminar_cotizacion_y_devolver_stock(cot['id_cotizacion'], usuario_activo):
                            st.success("Cotización eliminada y stock restituido.")
                            st.rerun()
        else:
            st.info("No hay cotizaciones registradas para este usuario.")

    # --- PESTAÑA 4: GESTIÓN DE USUARIOS (SOLO MAESTRO) ---
    if st.session_state.es_maestro:
        with tabs[3]:
            st.header("Crear Nuevo Usuario (Regular)")
            st.info("Los usuarios creados aquí tendrán su propio inventario y cotizaciones en la base de datos centralizada.")
            with st.form("form_nuevo_usuario"):
                nuevo_user = st.text_input("Nombre de Usuario (sin espacios preferiblemente):")
                nueva_pass = st.text_input("Contraseña:", type="password")
                btn_crear = st.form_submit_button("Crear Usuario")
                
                if btn_crear:
                    if nuevo_user and nueva_pass:
                        exito = crear_nuevo_usuario(nuevo_user.strip(), nueva_pass)
                        if exito:
                            st.success(f"¡Usuario '{nuevo_user}' creado correctamente!")
                        else:
                            st.error(f"El usuario '{nuevo_user}' ya existe en la base de datos.")
                    else:
                        st.warning("Por favor, completa ambos campos.")