document.addEventListener('DOMContentLoaded', () => {
  let currentProcessId = '';
  let currentProcessData = null;

  const processSelect = document.getElementById('process-select');
  const btnRefresh = document.getElementById('btn-refresh');
  const btnAudit = document.getElementById('btn-audit');
  const btnExport = document.getElementById('btn-export');
  const itemsContainer = document.getElementById('items-container');
  const fieldsContainer = document.getElementById('fields-container');
  const evidenceContainer = document.getElementById('evidence-container');
  const evidencePageTag = document.getElementById('evidence-page-tag');
  const itemsCount = document.getElementById('items-count');
  const fieldsCount = document.getElementById('fields-count');
  const statusSummary = document.getElementById('status-summary');

  const auditModal = document.getElementById('audit-modal');
  const modalClose = document.getElementById('modal-close');
  const modalOverlay = document.getElementById('modal-overlay');
  const auditTableBody = document.getElementById('audit-table-body');

  // Tabs
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    });
  });

  // Load Processes
  async function loadProcesses() {
    try {
      const res = await fetch('/api/processes');
      const data = await res.json();
      processSelect.innerHTML = '';
      if (!data || data.length === 0) {
        processSelect.innerHTML = '<option value="">Nenhum processo carregado</option>';
        return;
      }
      data.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = `${p.id} (${p.items_count} itens)`;
        processSelect.appendChild(opt);
      });
      currentProcessId = data[0].id;
      loadProcessDetail(currentProcessId);
    } catch (e) {
      console.error('Erro ao carregar processos:', e);
    }
  }

  // Load Process Detail
  async function loadProcessDetail(pid) {
    if (!pid) return;
    try {
      const res = await fetch(`/api/processes/${pid}`);
      currentProcessData = await res.json();
      renderProcessData(currentProcessData);
    } catch (e) {
      console.error('Erro ao carregar detalhes do processo:', e);
    }
  }

  function renderProcessData(proc) {
    let allItems = [];
    let allDocFields = [];

    let extCount = 0;
    let confCount = 0;
    let rejCount = 0;

    proc.documents.forEach(doc => {
      (doc.field_values || []).forEach(fv => {
        allDocFields.push({ docId: doc.id, fv });
        if (fv.review_status === 'EXTRACTED') extCount++;
        else if (fv.review_status === 'CONFIRMED') confCount++;
        else if (fv.review_status === 'REJECTED') rejCount++;
      });
      (doc.items || []).forEach(it => {
        allItems.push({ docId: doc.id, item: it });
        (it.field_values || []).forEach(fv => {
          if (fv.review_status === 'EXTRACTED') extCount++;
          else if (fv.review_status === 'CONFIRMED') confCount++;
          else if (fv.review_status === 'REJECTED') rejCount++;
        });
        (it.requirements || []).forEach(r => {
          if (r.review_status === 'EXTRACTED') extCount++;
          else if (r.review_status === 'CONFIRMED') confCount++;
          else if (r.review_status === 'REJECTED') rejCount++;
        });
      });
    });

    itemsCount.textContent = allItems.length;
    fieldsCount.textContent = allDocFields.length;
    statusSummary.innerHTML = `
      <span class="badge badge-extracted">${extCount} Extraídos</span>
      <span class="badge badge-confirmed">${confCount} Confirmados</span>
      <span class="badge badge-rejected">${rejCount} Rejeitados</span>
    `;

    renderItems(allItems);
    renderFields(allDocFields);

    // Auto-select first item if available
    if (allItems.length > 0) {
      const first = allItems[0];
      showItemEvidence(first.item, first.docId);
    }
  }

  function renderItems(itemsList) {
    itemsContainer.innerHTML = '';
    if (itemsList.length === 0) {
      itemsContainer.innerHTML = '<div class="empty-state">Nenhum item encontrado no processo.</div>';
      return;
    }

    itemsList.forEach(({ docId, item }) => {
      const card = document.createElement('div');
      card.className = 'item-card';
      card.dataset.itemId = item.id;

      let fieldsHtml = '';
      (item.field_values || []).forEach(fv => {
        const badgeClass = `badge-${fv.review_status.toLowerCase()}`;
        const targetId = `${docId}:${item.id}:${fv.field_type}`;
        fieldsHtml += `
          <div class="field-pill" data-target="${targetId}">
            <div class="field-pill-info">
              <span class="field-label">${fv.field_type}</span>
              <div class="field-val">${fv.value} ${fv.unit || ''}</div>
            </div>
            <div class="field-pill-actions">
              <span class="badge ${badgeClass}">${fv.review_status}</span>
              <button class="btn btn-sm btn-success btn-action" data-action="CONFIRM" data-target="${targetId}" title="Confirmar este campo">✓</button>
              <button class="btn btn-sm btn-action" data-action="EDIT_AND_CONFIRM" data-target="${targetId}" data-value="${fv.value}" data-unit="${fv.unit || ''}" title="Editar e confirmar">✎</button>
              <button class="btn btn-sm btn-danger btn-action" data-action="REJECT" data-target="${targetId}" title="Rejeitar este campo">✕</button>
            </div>
          </div>
        `;
      });

      (item.requirements || []).forEach(req => {
        const badgeClass = `badge-${req.review_status.toLowerCase()}`;
        const targetId = `${docId}:${item.id}:req:${req.attribute}`;
        fieldsHtml += `
          <div class="field-pill" data-target="${targetId}">
            <div class="field-pill-info">
              <span class="field-label">REQ: ${req.attribute.toUpperCase()}</span>
              <div class="field-val">${req.value} ${req.unit || ''}</div>
            </div>
            <div class="field-pill-actions">
              <span class="badge ${badgeClass}">${req.review_status}</span>
              <button class="btn btn-sm btn-success btn-action" data-action="CONFIRM" data-target="${targetId}" title="Confirmar este requisito">✓</button>
              <button class="btn btn-sm btn-action" data-action="EDIT_AND_CONFIRM" data-target="${targetId}" data-value="${req.value}" data-unit="${req.unit || ''}" title="Editar e confirmar">✎</button>
              <button class="btn btn-sm btn-danger btn-action" data-action="REJECT" data-target="${targetId}" title="Rejeitar este requisito">✕</button>
            </div>
          </div>
        `;
      });

      card.innerHTML = `
        <div class="item-header">
          <span class="item-title">${item.id.toUpperCase()}</span>
          <span class="badge badge-neutral">${docId.split(':').pop().toUpperCase()}</span>
        </div>
        <div class="item-desc">${item.description}</div>
        <div class="item-fields-grid">${fieldsHtml}</div>
      `;

      // Click card -> show item general evidence
      card.addEventListener('click', (e) => {
        if (e.target.closest('.field-pill') || e.target.tagName === 'BUTTON') return;
        document.querySelectorAll('.item-card').forEach(c => c.classList.remove('selected'));
        document.querySelectorAll('.field-pill').forEach(p => p.classList.remove('selected-pill'));
        card.classList.add('selected');
        showItemEvidence(item, docId);
      });

      // Click individual field pill -> show specific field evidence
      card.querySelectorAll('.field-pill').forEach(pill => {
        pill.addEventListener('click', (e) => {
          if (e.target.tagName === 'BUTTON') return;
          e.stopPropagation();
          document.querySelectorAll('.item-card').forEach(c => c.classList.remove('selected'));
          document.querySelectorAll('.field-pill').forEach(p => p.classList.remove('selected-pill'));
          card.classList.add('selected');
          pill.classList.add('selected-pill');

          const targetId = pill.dataset.target;
          showFieldPillEvidence(item, docId, targetId);
        });
      });

      // Actions on subfields
      card.querySelectorAll('.btn-action').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const action = btn.dataset.action;
          const target = btn.dataset.target;
          if (action === 'EDIT_AND_CONFIRM') {
            openEditModal(target, btn.dataset.value, btn.dataset.unit);
            return;
          }
          await submitReview(target, action);
        });
      });

      itemsContainer.appendChild(card);
    });
  }

  function renderFields(fieldsList) {
    fieldsContainer.innerHTML = '';
    if (fieldsList.length === 0) {
      fieldsContainer.innerHTML = '<div class="empty-state">Nenhum campo de nível documental.</div>';
      return;
    }

    fieldsList.forEach(({ docId, fv }) => {
      const card = document.createElement('div');
      card.className = 'item-card';
      const targetId = `${docId}:${fv.field_type}`;
      const badgeClass = `badge-${fv.review_status.toLowerCase()}`;

      card.innerHTML = `
        <div class="item-header">
          <span class="item-title">${fv.field_type}</span>
          <span class="badge ${badgeClass}">${fv.review_status}</span>
        </div>
        <div class="field-val" style="font-size:15px; margin-bottom:10px;">${fv.value} ${fv.unit || ''}</div>
        <div class="item-actions">
          <button class="btn btn-sm btn-success btn-action" data-action="CONFIRM" data-target="${targetId}">Confirmar (Aceitar)</button>
          <button class="btn btn-sm btn-action" data-action="EDIT_AND_CONFIRM" data-target="${targetId}" data-value="${fv.value}" data-unit="${fv.unit || ''}">Editar</button>
          <button class="btn btn-sm btn-danger btn-action" data-action="REJECT" data-target="${targetId}">Rejeitar</button>
        </div>
      `;

      card.addEventListener('click', (e) => {
        if (e.target.tagName === 'BUTTON') return;
        document.querySelectorAll('.item-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        showEvidenceView({
          label: `Campo Documental: ${fv.field_type}`,
          valueDisplay: `${fv.value} ${fv.unit || ''}`,
          evidence: fv.evidence,
          contextInfo: `Documento: ${docId}`,
        });
      });

      card.querySelectorAll('.btn-action').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const action = btn.dataset.action;
          const target = btn.dataset.target;
          if (action === 'EDIT_AND_CONFIRM') {
            openEditModal(target, btn.dataset.value, btn.dataset.unit);
            return;
          }
          await submitReview(target, action);
        });
      });

      fieldsContainer.appendChild(card);
    });
  }

  function showItemEvidence(item, docId) {
    showEvidenceView({
      label: `Item: ${item.id.toUpperCase()}`,
      valueDisplay: item.description,
      evidence: item.evidence,
      contextInfo: `Documento: ${docId}`,
      subFields: item.field_values,
      subReqs: item.requirements,
    });
  }

  function showFieldPillEvidence(item, docId, targetId) {
    const parts = targetId.split(':');
    let fv = null;
    let req = null;
    let fieldName = '';
    let valStr = '';
    let evList = [];

    if (targetId.includes(':req:')) {
      const attr = parts[parts.length - 1];
      req = (item.requirements || []).find(r => r.attribute.toLowerCase() === attr.toLowerCase());
      if (req) {
        fieldName = `Requisito: ${req.attribute.toUpperCase()}`;
        valStr = `${req.value} ${req.unit || ''}`;
        evList = req.evidence || [];
      }
    } else {
      const fType = parts[parts.length - 1];
      fv = (item.field_values || []).find(f => f.field_type === fType);
      if (fv) {
        fieldName = `Campo do Item: ${fv.field_type}`;
        valStr = `${fv.value} ${fv.unit || ''}`;
        evList = fv.evidence || [];
      }
    }

    showEvidenceView({
      label: `${fieldName} (${item.id.toUpperCase()})`,
      valueDisplay: valStr,
      evidence: evList,
      contextInfo: `Item: ${item.description}`,
    });
  }

  function showEvidenceView({ label, valueDisplay, evidence, contextInfo, subFields, subReqs }) {
    if (!evidence || evidence.length === 0) {
      evidenceContainer.innerHTML = `
        <div class="evidence-box">
          <div class="evidence-header-info">
            <span><strong>${label}</strong></span>
            <span class="badge badge-rejected">Sem Evidência</span>
          </div>
          <div style="margin-top:10px; color:#64748b;">Nenhuma evidência vinculada a este campo.</div>
        </div>
      `;
      evidencePageTag.textContent = 'Sem Evidência';
      return;
    }

    const ev = evidence[0];
    evidencePageTag.textContent = `${ev.document_id} • Página ${ev.page}`;

    let subSummaryHtml = '';
    if (subFields && subFields.length > 0) {
      subSummaryHtml += '<div style="margin-top:14px; font-size:12px; color:#475569;"><strong>Valores extraídos deste item (clique no cartão para ver cada evidência):</strong><ul style="margin-top:4px; padding-left:18px;">';
      subFields.forEach(f => {
        subSummaryHtml += `<li><code>${f.field_type}</code>: <strong>${f.value} ${f.unit || ''}</strong> (Página ${f.evidence[0]?.page || '?'})</li>`;
      });
      subSummaryHtml += '</ul></div>';
    }

    evidenceContainer.innerHTML = `
      <div class="evidence-box">
        <div class="evidence-header-info">
          <div>
            <div style="font-size:14px; font-weight:600; color:#1e293b;">${label}</div>
            <div style="font-size:12px; color:#64748b; margin-top:2px;">${contextInfo || ''}</div>
          </div>
          <div style="text-align:right;">
            <span class="badge badge-neutral">Pág. ${ev.page}</span>
            <div style="font-size:11px; font-family:monospace; color:#94a3b8; margin-top:2px;">${ev.block_id}</div>
          </div>
        </div>

        <div style="margin-top:10px; margin-bottom:6px; font-size:12px; font-weight:600; text-transform:uppercase; color:#64748b;">
          Trecho Original Ancorado no Documento:
        </div>
        <div class="quote-highlight">${ev.quote}</div>

        <div style="margin-top:12px; padding:8px 12px; background:#f1f5f9; border-radius:6px; font-size:13px;">
          <strong>Valor Estruturado:</strong> <span style="font-family:monospace; font-weight:600; color:#2563eb;">${valueDisplay}</span>
        </div>

        ${subSummaryHtml}
      </div>
    `;
  }

  async function submitReview(targetId, action, newVal = null, newUnit = null, quote = null) {
    const isReq = targetId.includes(':req:');
    const endpoint = isReq
      ? `/api/processes/${currentProcessId}/requirements/${encodeURIComponent(targetId)}/review`
      : `/api/processes/${currentProcessId}/fields/${encodeURIComponent(targetId)}/review`;

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: 'revisor_humano',
          action: action,
          new_value: newVal,
          new_unit: newUnit,
          new_evidence_quote: quote,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        return { ok: false, detail: err.detail || 'Falha ao aplicar ação' };
      }
      // Recarrega dados atualizados
      loadProcessDetail(currentProcessId);
      return { ok: true };
    } catch (e) {
      console.error('Erro ao enviar revisão:', e);
      return { ok: false, detail: 'Falha de rede ao enviar revisão' };
    }
  }

  // --- Edição com reancoragem obrigatória (FR-013) ---
  const editModal = document.getElementById('edit-modal');
  const editOverlay = document.getElementById('edit-overlay');
  const editClose = document.getElementById('edit-close');
  const editCancel = document.getElementById('edit-cancel');
  const editSave = document.getElementById('edit-save');
  const editValue = document.getElementById('edit-value');
  const editUnit = document.getElementById('edit-unit');
  const editBlock = document.getElementById('edit-block');
  const editQuote = document.getElementById('edit-quote');
  const editError = document.getElementById('edit-error');
  const editTargetLabel = document.getElementById('edit-target-label');
  let editTargetId = null;

  // A evidência tem de vir do documento dono do fato: um valor do TR não pode
  // ser sustentado por texto do ETP.
  function documentBlocks(targetId) {
    const blocos = [];
    (currentProcessData?.documents || []).forEach(doc => {
      if (targetId && !targetId.startsWith(`${doc.id}:`)) return;
      (doc.sections || []).forEach(sec => {
        (sec.blocks || []).forEach(b => blocos.push({ ...b, docId: doc.id }));
      });
    });
    return blocos;
  }

  function openEditModal(targetId, valorAtual, unidadeAtual) {
    editTargetId = targetId;
    editTargetLabel.textContent = targetId;
    editValue.value = valorAtual ?? '';
    editUnit.value = unidadeAtual ?? '';
    editError.textContent = '';

    const blocos = documentBlocks(targetId);
    editBlock.innerHTML = '';
    blocos.forEach((b, i) => {
      const opt = document.createElement('option');
      opt.value = String(i);
      const resumo = b.text.replace(/\s+/g, ' ').trim();
      opt.textContent = `${b.id} — ${resumo.slice(0, 60)}${resumo.length > 60 ? '…' : ''}`;
      editBlock.appendChild(opt);
    });
    editQuote.value = blocos.length ? blocos[0].text.trim() : '';
    editBlock.onchange = () => {
      const b = blocos[Number(editBlock.value)];
      editQuote.value = b ? b.text.trim() : '';
    };

    if (!blocos.length) {
      editError.textContent = 'Documento sem blocos ingeridos: não há trecho para ancorar.';
    }
    editModal.classList.add('active');
  }

  function closeEditModal() {
    editModal.classList.remove('active');
    editTargetId = null;
  }

  [editClose, editCancel, editOverlay].forEach(el => {
    if (el) el.addEventListener('click', closeEditModal);
  });

  editSave.addEventListener('click', async () => {
    if (!editTargetId) return;
    const quote = editQuote.value.trim();
    if (!quote) {
      editError.textContent = 'Informe o trecho do documento que sustenta o valor novo.';
      return;
    }
    const bruto = editValue.value.trim();
    const numero = Number(bruto);
    const valor = bruto !== '' && !Number.isNaN(numero) ? numero : bruto;

    const resultado = await submitReview(
      editTargetId,
      'EDIT_AND_CONFIRM',
      valor,
      editUnit.value.trim() || null,
      quote,
    );
    if (resultado && resultado.ok) {
      closeEditModal();
    } else {
      editError.textContent = resultado ? resultado.detail : 'Falha ao aplicar edição';
    }
  });

  // Audit modal
  btnAudit.addEventListener('click', async () => {
    if (!currentProcessId) return;
    try {
      const res = await fetch(`/api/processes/${currentProcessId}/audit`);
      const logs = await res.json();
      auditTableBody.innerHTML = '';
      if (!logs || logs.length === 0) {
        auditTableBody.innerHTML = '<tr><td colspan="7" class="text-center">Nenhum registro de auditoria neste processo.</td></tr>';
      } else {
        logs.forEach(l => {
          const tr = document.createElement('tr');
          const dt = new Date(l.timestamp).toLocaleString('pt-BR');
          tr.innerHTML = `
            <td>${dt}</td>
            <td><code>${l.user_id}</code></td>
            <td><code>${l.target_id}</code></td>
            <td><strong>${l.action}</strong></td>
            <td>${l.previous_value !== null ? l.previous_value : '-'}</td>
            <td>${l.new_value !== null ? l.new_value : '-'}</td>
            <td><span class="badge badge-${l.new_status.toLowerCase()}">${l.new_status}</span></td>
          `;
          auditTableBody.appendChild(tr);
        });
      }
      auditModal.classList.add('active');
    } catch (e) {
      console.error('Erro ao abrir audit:', e);
    }
  });

  modalClose.addEventListener('click', () => auditModal.classList.remove('active'));
  modalOverlay.addEventListener('click', () => auditModal.classList.remove('active'));

  btnRefresh.addEventListener('click', () => loadProcessDetail(currentProcessId));
  processSelect.addEventListener('change', (e) => {
    currentProcessId = e.target.value;
    loadProcessDetail(currentProcessId);
  });

  btnExport.addEventListener('click', async () => {
    if (!currentProcessId) return;
    window.open(`/api/processes/${currentProcessId}/confirmed`, '_blank');
  });

  loadProcesses();
});
