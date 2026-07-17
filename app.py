import streamlit as st
import pandas as pd
import io
import os

# Configuración de la página web
st.set_page_config(page_title="Generador de Cotizaciones", layout="wide")

st.title("📄 Sistema de Cotizaciones e Inventario")

# Nombre del archivo físico de datos
EXCEL_FILE = "COTIZACION.xlsx"

# --- FUNCIONES DE CONTROL DE DATOS ---

def cargar_datos_excel():
    """Carga las hojas del archivo Excel. Si no existe, crea datos por defecto."""
    if os.path.exists(EXCEL_FILE):
        try:
            df_inv = pd.read_excel(EXCEL_FILE, sheet_name="INVENTARIO")
            return df_inv
        except Exception as e:
            st.error(f"Error al leer el archivo Excel: {e}")
    
    # Inventario de respaldo si no existe el archivo
    return pd.DataFrame({
        'ID': [1, 2, 3, 4],
        'PRODUCTO': ['PRODUCTO-1', 'PRODUCTO-2', 'PRODUCTO-3', 'PRODUCTO-4'],
        'PRECIO': [100.0, 200.0, 300.0, 400.0]
    })

def guardar_inventario_excel(df_nuevo_inventario):
    """Sobrescribe la hoja INVENTARIO en el archivo Excel manteniendo intactas otras hojas."""
    try:
        # Intentamos preservar la hoja COTIZACION si ya existe en el archivo original
        hoja_cotizacion = pd.DataFrame()
        if os.path.exists(EXCEL_FILE):
            try:
                hoja_cotizacion = pd.read_excel(EXCEL_FILE, sheet_name="COTIZACION")
            except Exception:
                pass # Si no existe o está vacía, no pasa nada
        
        # Guardamos ambas hojas usando ExcelWriter
        with pd.ExcelWriter(EXCEL_FILE, engine='openpyxl') as writer:
            df_nuevo_inventario.to_excel(writer, sheet_name='INVENTARIO', index=False)
            if not hoja_cotizacion.empty:
                hoja_cotizacion.to_excel(writer, sheet_name='COTIZACION', index=False)
                
        st.success("¡Inventario actualizado y guardado con éxito en el archivo Excel!")
    except Exception as e:
        st.error(f"No se pudo guardar en el archivo Excel: {e}. Asegúrate de que el archivo no esté abierto en Excel.")

# Cargar inventario actual
if "df_inventario" not in st.session_state:
    st.session_state.df_inventario = cargar_datos_excel()

if "filas_cotizacion" not in st.session_state:
    st.session_state.filas_cotizacion = []


# --- INTERFAZ GRÁFICA CON PESTAÑAS (TABS) ---
tab1, tab2 = st.tabs(["🛒 Generar Cotización", "⚙️ Modificar Productos (Inventario)"])

# =====================================================================
# PESTAÑA 1: GENERAR COTIZACIÓN (SOLUCIÓN DEFINITIVA DE BOTÓN)
# =====================================================================
with tab1:
    st.subheader("Crear nueva cotización")
    
    df_inv_actual = st.session_state.df_inventario
    
    if df_inv_actual.empty:
        st.warning("El inventario está vacío. Agrega productos en la pestaña de Configuración.")
    else:
        # 1. Inicializar la llave del precio en el session_state si no existe
        if "precio_input" not in st.session_state:
            st.session_state.precio_input = float(df_inv_actual.iloc[0]["PRECIO"])

        # 2. Callback para actualizar el precio inmediatamente al cambiar de producto
        def al_cambiar_producto():
            prod_elegido = st.session_state.prod_select
            info_prod = df_inv_actual[df_inv_actual["PRODUCTO"] == prod_elegido].iloc[0]
            st.session_state.precio_input = float(info_prod["PRECIO"])

        # El selector de producto se queda fuera del formulario para mantener la reactividad del precio
        producto_seleccionado = st.selectbox(
            "Selecciona un Producto", 
            df_inv_actual["PRODUCTO"].tolist(), 
            key="prod_select",
            on_change=al_cambiar_producto
        )
        info_prod = df_inv_actual[df_inv_actual["PRODUCTO"] == producto_seleccionado].iloc[0]

        st.write("---")

        # 3. Creamos un formulario estable para recolectar los valores numéricos y el botón
        with st.form(key="formulario_agregar_producto"):
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                # Lee directamente del session_state controlado por el callback
                precio = st.number_input(
                    "Precio ($)", 
                    min_value=0.0, 
                    step=10.0, 
                    key="precio_input"
                )

            with col2:
                cantidad = st.number_input("Cantidad", value=1, min_value=1, step=1, key="cant_input")

            with col3:
                dias = st.number_input("Días", value=1, min_value=1, step=1, key="dias_input")

            with col4:
                descuento = st.number_input("Descuento (%)", value=0.0, min_value=0.0, max_value=100.0, step=5.0, key="desc_input")

            # Botón de envío del formulario (garantiza la ejecución segura del código)
            boton_enviar = st.form_submit_button(label="➕ Agregar a la tabla")

        # 4. Procesamos la lógica matemática solo si el formulario fue enviado con éxito
        if boton_enviar:
            subtotal_bruto = precio * cantidad * dias
            subtotal_con_descuento = subtotal_bruto * (1 - (descuento / 100))
            
            nueva_fila = {
                "ID": info_prod["ID"],
                "Producto": producto_seleccionado,
                "Precio": precio,
                "Cantidad": cantidad,
                "Días": dias,
                "Descuento": descuento,
                "Subtotal": round(subtotal_con_descuento, 2)
            }
            
            # Guardamos la información en nuestra lista global de cotizaciones
            st.session_state.filas_cotizacion.append(nueva_fila)
            st.success(f"¡{producto_seleccionado} agregado correctamente!")
            # Forzamos actualización visual limpia
            st.rerun()

    st.write("---")

    # 5. Despliegue y renderizado de la tabla de resultados acumulados
    if st.session_state.filas_cotizacion:
        st.subheader("📋 Tu Cotización")
        df_cotizacion = pd.DataFrame(st.session_state.filas_cotizacion)
        st.dataframe(df_cotizacion, use_container_width=True)
        
        total_general = df_cotizacion["Subtotal"].sum()
        st.metric(label="TOTAL GENERAL", value=f"${total_general:,.2f}")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🧹 Limpiar Cotización", key="btn_limpiar"):
                st.session_state.filas_cotizacion = []
                st.rerun()
        
        with col_btn2:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df_cotizacion.to_excel(writer, sheet_name='COTIZACION', index=False)
                df_total = pd.DataFrame([{"ID": "Total", "Subtotal": total_general}])
                df_total.to_excel(writer, sheet_name='COTIZACION', startrow=len(df_cotizacion)+2, index=False)
                
            st.download_button(
                label="📥 Descargar Cotización en Excel",
                data=buffer.getvalue(),
                file_name="COTIZACION_GENERADA.xlsx",
                mime="application/vnd.ms-excel",
                key="btn_descarga"
            )

# =====================================================================
# PESTAÑA 2: GESTIONAR INVENTARIO (MODIFICAR PRODUCTOS)
# =====================================================================
with tab2:
    st.subheader("⚙️ Panel de Control del Inventario")
    st.write("Modifica los nombres, precios o IDs directamente en la tabla interactiva y haz clic en 'Guardar Cambios'.")
    
    # Usamos st.data_editor para permitir la edición directa de la tabla en pantalla
    df_editable = st.data_editor(
        st.session_state.df_inventario, 
        num_rows="dynamic", # Permite añadir y eliminar filas dinámicamente
        use_container_width=True,
        key="editor_inventario"
    )
    
    # Botón para guardar los cambios tanto en la sesión activa como en el Excel físico
    if st.button("💾 Guardar Cambios en Excel"):
        st.session_state.df_inventario = df_editable
        guardar_inventario_excel(df_editable)
        st.rerun()