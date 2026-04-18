/* =========================================================
   CuentaLuz Chile – JavaScript principal
   Responsabilidades:
   1. Tabs calculadora (kWh directo vs. aparatos)
   2. Contador de kWh en tiempo real (modo aparatos)
   3. Toggle visual de tarjetas de aparatos
   4. Info box BT2
   ========================================================= */

// ─── Utilidades ───────────────────────────────────────────

function fmtKwh(valor) {
  return valor.toFixed(1) + ' kWh/mes';
}

// ─── Tabs ─────────────────────────────────────────────────

function switchTab(modo) {
  const panelKwh      = document.getElementById('panel-kwh');
  const panelAparatos = document.getElementById('panel-aparatos');
  const tabKwh        = document.getElementById('tab-kwh');
  const tabAparatos   = document.getElementById('tab-aparatos');
  const modoInput     = document.getElementById('modo-input');

  if (!panelKwh || !panelAparatos) return;

  if (modo === 'kwh') {
    panelKwh.classList.remove('hidden');
    panelAparatos.classList.add('hidden');

    tabKwh.classList.add('text-electric-600', 'border-electric-600', 'bg-white');
    tabKwh.classList.remove('text-gray-500', 'border-transparent');
    tabAparatos.classList.remove('text-electric-600', 'border-electric-600', 'bg-white');
    tabAparatos.classList.add('text-gray-500', 'border-transparent');
  } else {
    panelAparatos.classList.remove('hidden');
    panelKwh.classList.add('hidden');

    tabAparatos.classList.add('text-electric-600', 'border-electric-600', 'bg-white');
    tabAparatos.classList.remove('text-gray-500', 'border-transparent');
    tabKwh.classList.remove('text-electric-600', 'border-electric-600', 'bg-white');
    tabKwh.classList.add('text-gray-500', 'border-transparent');
  }

  if (modoInput) modoInput.value = modo;
}

// ─── Aparatos: estado visual de tarjeta ───────────────────

function actualizarTarjeta(item) {
  const checkbox = item.querySelector('.aparato-check');
  const card     = item.querySelector('.aparato-card');
  if (!checkbox || !card) return;

  if (checkbox.checked) {
    card.classList.add('border-electric-500', 'bg-electric-50');
    card.classList.remove('border-gray-200');
  } else {
    card.classList.remove('border-electric-500', 'bg-electric-50');
    card.classList.add('border-gray-200');
  }
}

// ─── Aparatos: cálculo en tiempo real ─────────────────────

function calcularKwhAparatos() {
  const items = document.querySelectorAll('.aparato-item');
  let total = 0;

  items.forEach(item => {
    const checkbox = item.querySelector('.aparato-check');
    const horasInput = item.querySelector('.horas-input');
    const potencia   = parseFloat(item.dataset.potenciaW || 0);
    const kwhDisplay = item.querySelector('.aparato-kwh');

    if (!checkbox || !horasInput) return;

    const horas = parseFloat(horasInput.value) || 0;
    const kwh   = (potencia / 1000) * horas * 30;

    // Mostrar kWh parcial en la tarjeta
    if (kwhDisplay) {
      kwhDisplay.textContent = checkbox.checked ? '~' + kwh.toFixed(1) + ' kWh' : '';
    }

    if (checkbox.checked) {
      total += kwh;
    }
  });

  const badge = document.getElementById('kwh-live-badge');
  if (badge) {
    badge.textContent = fmtKwh(total);
    badge.classList.toggle('bg-green-600', total > 0);
    badge.classList.toggle('bg-electric-600', total === 0);
  }

  return total;
}

// ─── BT2 info box ─────────────────────────────────────────

function toggleBT2Info() {
  const select  = document.getElementById('tarifa-select');
  const infoBox = document.getElementById('bt2-info');
  if (!select || !infoBox) return;
  infoBox.classList.toggle('hidden', select.value !== 'BT2');
}

// ─── Selector de comunas ──────────────────────────────────

const DIST_NOMBRES = {
  enel:       'Enel (RM)',
  cge:        'CGE',
  chilquinta: 'Chilquinta (V Región)',
  frontel:    'Frontel (La Araucanía)',
};

const DIST_VIGENCIA = {
  enel:       'Tarifas verificadas — vigentes desde 01-04-2026',
  cge:        'Tarifas verificadas — datos marzo 2025',
  chilquinta: 'Tarifas verificadas — vigentes desde 01-03-2026',
  frontel:    'Tarifas verificadas — vigentes desde 01-04-2026',
};

function normalizarTexto(s) {
  return s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function buscarComuna(nombre) {
  if (!window.COMUNAS_DATA || !nombre.trim()) return null;
  const target = normalizarTexto(nombre.trim());
  return window.COMUNAS_DATA.find(c => normalizarTexto(c.nombre) === target) || null;
}

function onComunaChange() {
  const input      = document.getElementById('comuna-input');
  const okIcon     = document.getElementById('comuna-ok');
  const distLabel  = document.getElementById('dist-resuelta');
  const fallback   = document.getElementById('dist-fallback');
  const distSelect = document.getElementById('distribuidora-select');
  const vigencia   = document.getElementById('tarifa-vigencia');

  if (!input) return;
  const comuna = buscarComuna(input.value);

  if (comuna) {
    // Encontrada: mostrar confirmación y ocultar fallback
    const distNombre = DIST_NOMBRES[comuna.distribuidora_id] || comuna.distribuidora_id;
    distLabel.textContent = `Distribuidora: ${distNombre}`;
    distLabel.classList.remove('hidden');
    fallback.classList.add('hidden');
    okIcon.classList.remove('hidden');

    // Sincronizar el select de fallback (aunque esté oculto) para que el POST tenga el valor
    if (distSelect) distSelect.value = comuna.distribuidora_id;

    // Mostrar vigencia
    const msg = DIST_VIGENCIA[comuna.distribuidora_id];
    if (vigencia) {
      vigencia.textContent = msg || 'Tarifas estimadas — pendiente decreto oficial';
    }
  } else if (input.value.trim() === '') {
    distLabel.classList.add('hidden');
    fallback.classList.remove('hidden');
    okIcon.classList.add('hidden');
    if (vigencia) vigencia.textContent = '';
  } else {
    // Texto ingresado pero no se encontró la comuna
    distLabel.textContent = 'Comuna no reconocida — selecciona la distribuidora abajo';
    distLabel.classList.remove('hidden');
    distLabel.classList.add('text-amber-600');
    distLabel.classList.remove('text-electric-600');
    fallback.classList.remove('hidden');
    okIcon.classList.add('hidden');
    if (vigencia) vigencia.textContent = '';
  }
}

// ─── Validación del formulario ────────────────────────────

function validarFormulario(e) {
  const modo = document.getElementById('modo-input')?.value;

  if (modo === 'kwh') {
    const val = parseFloat(document.getElementById('kwh-directo-input')?.value);
    if (!val || val <= 0) {
      e.preventDefault();
      const input = document.getElementById('kwh-directo-input');
      input?.classList.add('ring-2', 'ring-red-400', 'border-red-400');
      input?.focus();
      return;
    }
  } else {
    // Verificar que haya al menos un aparato seleccionado
    const checks = document.querySelectorAll('.aparato-check:checked');
    if (checks.length === 0) {
      e.preventDefault();
      alert('Selecciona al menos un aparato para estimar tu consumo.');
    }
  }
}

// ─── Inicialización ───────────────────────────────────────

document.addEventListener('DOMContentLoaded', function () {

  // Listener en aparatos
  document.querySelectorAll('.aparato-item').forEach(item => {
    const checkbox   = item.querySelector('.aparato-check');
    const horasInput = item.querySelector('.horas-input');
    const card       = item.querySelector('.aparato-card');

    if (checkbox) {
      checkbox.addEventListener('change', () => {
        actualizarTarjeta(item);
        calcularKwhAparatos();
      });
    }

    if (horasInput) {
      horasInput.addEventListener('input', calcularKwhAparatos);
    }

    // Click en la tarjeta (fuera del checkbox) también lo activa
    if (card) {
      card.addEventListener('click', function (e) {
        if (e.target === horasInput || e.target === checkbox) return;
        if (e.target.closest('.horas-input') || e.target.closest('.aparato-check')) return;
        if (checkbox) {
          checkbox.checked = !checkbox.checked;
          actualizarTarjeta(item);
          calcularKwhAparatos();
        }
      });
    }
  });

  // Estado inicial de tarjetas (para precargados)
  document.querySelectorAll('.aparato-item').forEach(actualizarTarjeta);
  calcularKwhAparatos();

  // Listener selector de tarifa
  const tarifaSelect = document.getElementById('tarifa-select');
  if (tarifaSelect) {
    tarifaSelect.addEventListener('change', toggleBT2Info);
    toggleBT2Info(); // estado inicial
  }

  // Listener buscador de comunas
  const comunaInput = document.getElementById('comuna-input');
  if (comunaInput) {
    comunaInput.addEventListener('input', onComunaChange);
    comunaInput.addEventListener('change', onComunaChange);
    onComunaChange(); // estado inicial
  }

  // Validación del form
  const form = document.getElementById('calc-form');
  if (form) form.addEventListener('submit', validarFormulario);

  // Limpiar estilo error al escribir
  const kwhInput = document.getElementById('kwh-directo-input');
  if (kwhInput) {
    kwhInput.addEventListener('input', () => {
      kwhInput.classList.remove('ring-2', 'ring-red-400', 'border-red-400');
    });
  }
});
