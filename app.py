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

UNIDADES_MEDIDA = ["piezas", "horas", "metros cuadrados", "evento", "paquete"]

def hash_password(password: str) -> str:
    """Encripta la contraseña usando SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def obtener_conexion():
    """Crea la carpeta de datos si no existe y retorna la conexión a SQLite."""
    if not os.path.exists(CARPETA_DATOS):
        os.makedirs(CARPETA_DATOS)
    return sqlite3.connect(DB_HISTORIAL)

def inicializar_db_segura():
    """Crea las tablas e integra migraciones de columnas si no existen."""
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
            productos_json TEXT NOT NULL,
            descuento_global REAL DEFAULT 0.0
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

    # Tabla de inventario centralizada
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventario (
            id TEXT NOT NULL,
            usuario TEXT NOT NULL,
            producto TEXT NOT NULL,
            descripcion TEXT,
            unidad_medida TEXT NOT NULL DEFAULT 'piezas',
            precio_base REAL NOT NULL,
            precio_venta REAL NOT NULL,
            stock INTEGER NOT NULL,
            comentarios TEXT,
            PRIMARY KEY (id, usuario)
        )
    ''')
    
    # Migraciones automáticas de esquema
    cursor.execute("PRAGMA table_info(inventario)")
    col_inv = [info[1] for info in cursor.fetchall()]
    if "descripcion" not in col_inv:
        cursor.execute("ALTER TABLE inventario ADD COLUMN descripcion TEXT")
    if "unidad_medida" not in col_inv:
        cursor.execute("ALTER TABLE inventario ADD COLUMN unidad_medida TEXT NOT NULL DEFAULT 'piezas'")
        
    cursor.execute("PRAGMA table_info(historial)")
    col_hist = [info[1] for info in cursor.fetchall()]
    if "descuento_global" not in col_hist:
        cursor.execute("ALTER TABLE historial ADD COLUMN descuento_global REAL DEFAULT 0.0")
    
    # Crear usuario maestro por defecto si no existen registros
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
    """Carga el inventario del usuario desde SQLite."""
    conn = obtener_conexion()
    query = """
        SELECT id AS ID, producto AS PRODUCTO, descripcion AS DESCRIPCION,
               unidad_medida AS UNIDAD, precio_base AS PRECIO_BASE, 
               precio_venta AS PRECIO_VENTA, stock AS STOCK, comentarios AS COMENTARIOS 
        FROM inventario WHERE usuario = ?
    """
    df = pd.read_sql_query(query, conn, params=(usuario,))
    
    if df.empty:
        df_base = pd.DataFrame({
            "ID": ["P-1", "P-2"],
            "usuario": [usuario, usuario],
            "PRODUCTO": ["Producto Demo 1", "Servicio Demo 2"],
            "DESCRIPCION": ["Descripción de prueba 1", "Descripción de servicio por hora"],
            "UNIDAD": ["piezas", "horas"],
            "PRECIO_BASE": [50.0, 100.0],
            "PRECIO_VENTA": [80.0, 150.0],
            "STOCK": [20, 15],
            "COMENTARIOS": ["Stock inicial", "Servicio básico"]
        })
        cursor = conn.cursor()
        for _, row in df_base.iterrows():
            cursor.execute('''
                INSERT OR REPLACE INTO inventario 
                (id, usuario, producto, descripcion, unidad_medida, precio_base, precio_venta, stock, comentarios)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (row["ID"], usuario, row["PRODUCTO"], row["DESCRIPCION"], row["UNIDAD"], 
                  row["PRECIO_BASE"], row["PRECIO_VENTA"], row["STOCK"], row["COMENTARIOS"]))
        conn.commit()
        df = pd.read_sql_query(query, conn, params=(usuario,))
    
    conn.close()
    return df

def agregar_producto_usuario(usuario: str, id_prod: str, nombre: str, descripcion: str, unidad: str, p_base: float, p_venta: float, stock: int, comentarios: str):
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO inventario 
        (id, usuario, producto, descripcion, unidad_medida, precio_base, precio_venta, stock, comentarios)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (id_prod, usuario, nombre, descripcion, unidad, p_base, p_venta, stock, comentarios))
    conn.commit()
    conn.close()

def eliminar_producto_usuario(usuario: str, id_prod: str):
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM inventario WHERE id = ? AND usuario = ?', (id_prod, usuario))
    conn.commit()
    conn.close()

def actualizar_stock_usuario(usuario: str, id_prod: str, cantidad_descontar: int):
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

def guardar_cotizacion_bd(usuario: str, cliente: str, total: float, descuento_global: float, productos: list) -> str:
    conn = obtener_conexion()
    cursor = conn.cursor()
    fecha_str = datetime.now().strftime("%Y%m%d%H%M%S")
    id_cot = f"COT-{fecha_str}"
    fecha_format = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute('''
        INSERT INTO historial (id_cotizacion, usuario, fecha, cliente, total, productos_json, descuento_global)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (id_cot, usuario, fecha_format, cliente, total, json.dumps(productos), descuento_global))
    conn.commit()
    conn.close()
    return id_cot

def obtener_historial_usuario(usuario: str) -> list:
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT id_cotizacion, fecha, cliente, total, productos_json, descuento_global FROM historial WHERE usuario = ? ORDER BY fecha DESC', (usuario,))
    registros = cursor.fetchall()
    conn.close()
    resultado = []
    for reg in registros:
        resultado.append({
            "id_cotizacion": reg[0],
            "fecha": reg[1],
            "cliente": reg[2],
            "total": reg[3],
            "productos": json.loads(reg[4]),
            "descuento_global": reg[5] if len(reg) > 5 and reg[5] is not None else 0.0
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
    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute('SELECT es_maestro FROM usuarios WHERE usuario = ? AND password = ?', (usuario, hash_password(password)))
    row = cursor.fetchone()
    conn.close()
    if row is not None:
        return {"valido": True, "es_maestro": bool(row[0])}
    return {"valido": False, "es_maestro": False}

def crear_nuevo_usuario(nuevo_usuario: str, password: str) -> bool:
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
# 5. GENERACIÓN DE PDFS INDIVIDUALES Y GENERALES
# ==========================================

def generar_pdf_individual(cotizacion: dict, usuario: str) -> bytes:
    """Genera un archivo PDF únicamente para una cotización seleccionada."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elementos = []
    estilos = getSampleStyleSheet()
    
    elementos.append(Paragraph(f"<b>REPORTE DE COTIZACIÓN</b>", estilos['Title']))
    elementos.append(Paragraph(f"<b>ID Cotización:</b> {cotizacion['id_cotizacion']} | <b>Usuario:</b> {usuario}", estilos['Normal']))
    elementos.append(Paragraph(f"<b>Cliente:</b> {cotizacion['cliente']} | <b>Fecha:</b> {cotizacion['fecha']}", estilos['Normal']))
    elementos.append(Spacer(1, 15))
    
    datos_tabla = [["ID", "Producto", "Unidad", "Cant.", "Días", "P. Unit", "Desc.", "Subtotal"]]
    subtotal_acumulado = 0.0
    
    for p in cotizacion['productos']:
        dias = p.get('dias', 1)
        desc = p.get('descuento_pct', 0.0)
        subtotal_item = p.get('subtotal', p['cantidad'] * p['precio'])
        subtotal_acumulado += subtotal_item
        datos_tabla.append([
            str(p['id']), str(p['nombre']), str(p.get('unidad', 'piezas')),
            str(p['cantidad']), str(dias), f"${p['precio']:.2f}",
            f"{desc}%", f"${subtotal_item:.2f}"
        ])
    
    desc_global = cotizacion.get('descuento_global', 0.0)
    if desc_global > 0:
        monto_desc_global = subtotal_acumulado * (desc_global / 100.0)
        datos_tabla.append(["", "", "", "", "", "", "Subtotal:", f"${subtotal_acumulado:.2f}"])
        datos_tabla.append(["", "", "", "", "", "", f"Desc. Global ({desc_global}%):", f"-${monto_desc_global:.2f}"])
    
    datos_tabla.append(["", "", "", "", "", "", "TOTAL:", f"${cotizacion['total']:.2f}"])
    
    tabla = Table(datos_tabla, colWidths=[40, 130, 60, 40, 40, 60, 50, 70])
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTNAME', (-2, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (-2, -1), (-1, -1), colors.HexColor("#ECF0F1")),
    ]))
    elementos.append(tabla)
    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()

def generar_pdf_general_paginado(historial: list, usuario: str) -> bytes:
    """Genera un archivo PDF consolidado con todas las cotizaciones."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elementos = []
    estilos = getSampleStyleSheet()
    
    for idx, cot in enumerate(historial):
        elementos.append(Paragraph(f"<b>REPORTE DE COTIZACIÓN</b>", estilos['Title']))
        elementos.append(Paragraph(f"<b>ID Cotización:</b> {cot['id_cotizacion']} | <b>Usuario:</b> {usuario}", estilos['Normal']))
        elementos.append(Paragraph(f"<b>Cliente:</b> {cot['cliente']} | <b>Fecha:</b> {cot['fecha']}", estilos['Normal']))
        elementos.append(Spacer(1, 15))
        
        datos_tabla = [["ID", "Producto", "Unidad", "Cant.", "Días", "P. Unit", "Desc.", "Subtotal"]]
        subtotal_acumulado = 0.0
        for p in cot['productos']:
            dias = p.get('dias', 1)
            desc = p.get('descuento_pct', 0.0)
            subtotal_item = p.get('subtotal', p['cantidad'] * p['precio'])
            subtotal_acumulado += subtotal_item
            datos_tabla.append([
                str(p['id']), str(p['nombre']), str(p.get('unidad', 'piezas')),
                str(p['cantidad']), str(dias), f"${p['precio']:.2f}",
                f"{desc}%", f"${subtotal_item:.2f}"
            ])
            
        desc_global = cot.get('descuento_global', 0.0)
        if desc_global > 0:
            monto_desc_global = subtotal_acumulado * (desc_global / 100.0)
            datos_tabla.append(["", "", "", "", "", "", "Subtotal:", f"${subtotal_acumulado:.2f}"])
            datos_tabla.append(["", "", "", "", "", "", f"Desc. Global ({desc_global}%):", f"-${monto_desc_global:.2f}"])
            
        datos_tabla.append(["", "", "", "", "", "", "TOTAL:", f"${cot['total']:.2f}"])
        
        tabla = Table(datos_tabla, colWidths=[40, 130, 60, 40, 40, 60, 50, 70])
        tabla.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTNAME', (-2, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (-2, -1), (-1, -1), colors.HexColor("#ECF0F1")),
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
        
        if not df_inventario.empty:
            prod_sel = st.selectbox("Producto:", df_inventario["PRODUCTO"].tolist())
            row = df_inventario[df_inventario["PRODUCTO"] == prod_sel].iloc[0]
            
            # Muestra del precio antes de agregar al carrito
            st.info(f"💵 **Precio Venta:** ${float(row['PRECIO_VENTA']):,.2f} | 📏 **Unidad:** {row['UNIDAD']} | 📦 **Stock Disponible:** {row['STOCK']}\n\n📝 **Descripción:** {row['DESCRIPCION']}")
            
            c1, c2, c3 = st.columns(3)
            cant_sel = c1.number_input("Cantidad Inicial:", min_value=1, value=1)
            dias_sel = c2.number_input("Días Iniciales:", min_value=1, value=1)
            desc_sel = c3.number_input("Descuento Item (%):", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
            
            if "carrito" not in st.session_state:
                st.session_state.carrito = []
                
            if st.button("➕ Agregar al Carrito"):
                if cant_sel <= row["STOCK"]:
                    precio = float(row["PRECIO_VENTA"])
                    monto_base = precio * cant_sel * dias_sel
                    monto_descuento = monto_base * (desc_sel / 100.0)
                    subtotal = monto_base - monto_descuento
                    
                    st.session_state.carrito.append({
                        "id": row["ID"],
                        "nombre": row["PRODUCTO"],
                        "unidad": row["UNIDAD"],
                        "precio": precio,
                        "cantidad": int(cant_sel),
                        "dias": int(dias_sel),
                        "descuento_pct": float(desc_sel),
                        "subtotal": subtotal
                    })
                    st.success("Producto agregado al carrito.")
                    st.rerun()
                else:
                    st.error("Stock insuficiente.")
        else:
            st.warning("No hay productos registrados en el inventario.")

        # --- SECCIÓN DE EDICIÓN Y GESTIÓN DE CARRITO ---
        if "carrito" in st.session_state and st.session_state.carrito:
            st.divider()
            st.subheader("🛒 Carrito de Cotización")
            
            indices_a_eliminar = []
            
            # Recorrer productos agregados para permitir edición o eliminación individual
            for idx, item in enumerate(st.session_state.carrito):
                with st.expander(f"📦 {item['nombre']} (ID: {item['id']}) - P. Unit: ${item['precio']:,.2f}", expanded=True):
                    col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 1])
                    
                    st.session_state.carrito[idx]["cantidad"] = col1.number_input(
                        "Cantidad", min_value=1, value=int(item["cantidad"]), key=f"cant_{idx}"
                    )
                    st.session_state.carrito[idx]["dias"] = col2.number_input(
                        "Días", min_value=1, value=int(item["dias"]), key=f"dias_{idx}"
                    )
                    st.session_state.carrito[idx]["descuento_pct"] = col3.number_input(
                        "Desc. Item (%)", min_value=0.0, max_value=100.0, value=float(item["descuento_pct"]), step=0.5, key=f"desc_{idx}"
                    )
                    
                    # Recálculo de subtotal por producto
                    p_unit = item["precio"]
                    c_val = st.session_state.carrito[idx]["cantidad"]
                    d_val = st.session_state.carrito[idx]["dias"]
                    desc_val = st.session_state.carrito[idx]["descuento_pct"]
                    
                    subtotal_actual = (p_unit * c_val * d_val) * (1 - (desc_val / 100.0))
                    st.session_state.carrito[idx]["subtotal"] = subtotal_actual
                    
                    col4.markdown(f"**Subtotal:**\n\n${subtotal_actual:,.2f}")
                    
                    if col5.button("🗑️", key=f"del_cart_{idx}"):
                        indices_a_eliminar.append(idx)

            # Procesar eliminaciones individuales
            if indices_a_eliminar:
                for index in sorted(indices_a_eliminar, reverse=True):
                    st.session_state.carrito.pop(index)
                st.rerun()

            # Resumen de totales y Descuento Global
            if st.session_state.carrito:
                subtotal_general = sum(item["subtotal"] for item in st.session_state.carrito)
                
                st.divider()
                st.subheader("💰 Totales y Descuento Global")
                c_desc1, c_desc2 = st.columns(2)
                c_desc1.metric("Subtotal Carrito", f"${subtotal_general:,.2f}")
                
                desc_global_input = c_desc2.number_input(
                    "Descuento Global (%):", min_value=0.0, max_value=100.0, value=0.0, step=0.5
                )
                
                monto_desc_global = subtotal_general * (desc_global_input / 100.0)
                total_final = subtotal_general - monto_desc_global
                
                st.markdown(f"### **Total Final a Cotizar:** `${total_final:,.2f}`")
                
                col_btn1, col_btn2 = st.columns(2)
                if col_btn1.button("🗑️ Vaciar Carrito Completo"):
                    st.session_state.carrito = []
                    st.rerun()

                if col_btn2.button("💾 Finalizar y Guardar Cotización"):
                    if cliente:
                        for item in st.session_state.carrito:
                            actualizar_stock_usuario(usuario_activo, item["id"], item["cantidad"])
                        id_generado = guardar_cotizacion_bd(usuario_activo, cliente, total_final, desc_global_input, st.session_state.carrito)
                        st.session_state.carrito = []
                        st.success(f"Cotización {id_generado} guardada con éxito.")
                        st.rerun()
                    else:
                        st.warning("Por favor, ingresa el nombre del cliente.")

    # --- PESTAÑA 2: INVENTARIO ---
    with tabs[1]:
        st.header("Inventario de Productos")
        st.dataframe(df_inventario, use_container_width=True)
        
        st.divider()
        col_izq, col_der = st.columns(2)
        
        # --- SECCIÓN AÑADIR PRODUCTO ---
        with col_izq:
            st.subheader("➕ Añadir Nuevo Producto")
            siguiente_id = obtener_siguiente_id(df_inventario)
            st.text_input("ID de Producto (Autogenerado):", value=siguiente_id, disabled=True)
            nuevo_nombre = st.text_input("Nombre del Producto:")
            nueva_desc = st.text_area("Descripción:")
            nueva_unidad = st.selectbox("Unidad de Medida:", UNIDADES_MEDIDA, key="add_unidad")
            
            c_a, c_b, c_c = st.columns(3)
            p_base = c_a.number_input("Precio Base:", min_value=0.0, value=10.0)
            p_venta = c_b.number_input("Precio Venta:", min_value=0.0, value=15.0)
            stock_i = c_c.number_input("Stock Inicial:", min_value=0, value=10)
            comentarios = st.text_input("Comentarios:")
            
            if st.button("💾 Guardar Nuevo Producto"):
                if nuevo_nombre:
                    agregar_producto_usuario(usuario_activo, siguiente_id, nuevo_nombre, nueva_desc, nueva_unidad, p_base, p_venta, stock_i, comentarios)
                    st.success("Producto registrado correctamente.")
                    st.rerun()
                else:
                    st.warning("Por favor, ingresa el nombre del producto.")

        # --- SECCIÓN MODIFICAR / ELIMINAR PRODUCTO ---
        with col_der:
            st.subheader("✏️ Modificar o Eliminar Producto")
            if not df_inventario.empty:
                prod_mod_sel = st.selectbox("Selecciona Producto a Modificar:", df_inventario["PRODUCTO"].tolist(), key="mod_sel")
                row_mod = df_inventario[df_inventario["PRODUCTO"] == prod_mod_sel].iloc[0]
                
                st.text_input("ID (No modificable):", value=row_mod["ID"], disabled=True, key="mod_id")
                edit_nombre = st.text_input("Nombre del Producto:", value=row_mod["PRODUCTO"], key="edit_nom")
                edit_desc = st.text_area("Descripción:", value=str(row_mod["DESCRIPCION"]), key="edit_desc")
                
                idx_unidad = UNIDADES_MEDIDA.index(row_mod["UNIDAD"]) if row_mod["UNIDAD"] in UNIDADES_MEDIDA else 0
                edit_unidad = st.selectbox("Unidad de Medida:", UNIDADES_MEDIDA, index=idx_unidad, key="edit_uni")
                
                m_a, m_b, m_c = st.columns(3)
                edit_p_base = m_a.number_input("Precio Base:", min_value=0.0, value=float(row_mod["PRECIO_BASE"]), key="edit_pb")
                edit_p_venta = m_b.number_input("Precio Venta:", min_value=0.0, value=float(row_mod["PRECIO_VENTA"]), key="edit_pv")
                edit_stock = m_c.number_input("Stock:", min_value=0, value=int(row_mod["STOCK"]), key="edit_st")
                edit_coment = st.text_input("Comentarios:", value=str(row_mod["COMENTARIOS"]), key="edit_com")
                
                btn_c1, btn_c2 = st.columns(2)
                if btn_c1.button("✏️ Actualizar Producto"):
                    agregar_producto_usuario(usuario_activo, row_mod["ID"], edit_nombre, edit_desc, edit_unidad, edit_p_base, edit_p_venta, edit_stock, edit_coment)
                    st.success("Producto actualizado correctamente.")
                    st.rerun()
                    
                if btn_c2.button("🗑️ Eliminar Producto"):
                    eliminar_producto_usuario(usuario_activo, row_mod["ID"])
                    st.success("Producto eliminado del inventario.")
                    st.rerun()
            else:
                st.info("No hay productos disponibles para editar.")

    # --- PESTAÑA 3: HISTORIAL ---
    with tabs[2]:
        st.header("Historial de Cotizaciones")
        historial = obtener_historial_usuario(usuario_activo)
        if historial:
            pdf_general_bytes = generar_pdf_general_paginado(historial, usuario_activo)
            st.download_button(
                label="📄 Descargar Todo el Historial (PDF Consolidado)", data=pdf_general_bytes,
                file_name=f"Reporte_General_{usuario_activo}.pdf", mime="application/pdf"
            )
            st.divider()
            for cot in historial:
                c1, c2, c3 = st.columns([3, 1.5, 1])
                with c1:
                    st.markdown(f"**ID:** `{cot['id_cotizacion']}` | **Cliente:** {cot['cliente']} | **Fecha:** {cot['fecha']} | **Total:** `${cot['total']:,.2f}`")
                with c2:
                    pdf_ind_bytes = generar_pdf_individual(cot, usuario_activo)
                    st.download_button(
                        label="📄 Descargar PDF",
                        data=pdf_ind_bytes,
                        file_name=f"{cot['id_cotizacion']}.pdf",
                        mime="application/pdf",
                        key=f"pdf_ind_{cot['id_cotizacion']}"
                    )
                with c3:
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