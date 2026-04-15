import { useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import EquipamentoSelector from '../../components/EquipamentoSelector';
import PDFSimulacao from '../../components/GenePDF';
import { FinanceiroInput, NumericInput, Radio } from '../../components/Inputs';
import { useLocalSearchParams, useRouter } from "expo-router";

const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
const API_BASE_URL = "/api"

const equipamentos_URL = `${API_BASE_URL}/equipamentos/`;
const tipo_equipamento_URL = `${API_BASE_URL}/tiposEquipamento/`;
const marca_equipamento_URL = `${API_BASE_URL}/marcasEquipamento/`;

const parseSafeNumber = (val) => {
  if (typeof val === 'number') return val;
  if (!val) return 0;
  let str = String(val);
  if (str.includes(',') && str.includes('.')) {
    str = str.replace(/\./g, '').replace(',', '.');
  } else if (str.includes(',')) {
    str = str.replace(',', '.');
  }
  return Number(str.replace(/[^\d.-]/g, '')) || 0;
};

export default function App() {
  const taxa = 0.0292;
  const router = useRouter(); 
  
  const [equipamentos, setEquipamentos] = useState([]);
  const [grupos, setGrupos] = useState([]);
  const [marcas, setMarcas] = useState([]);
  const [loading, setLoading] = useState(true);

  const [nomeVendedor, setNomeVendedor] = useState('');
  const [erroNomeVendedor, setErroNomeVendedor] = useState(false);
  const [nomeCNPJ, setNomeCNPJ] = useState('');
  const [erroNomeCNPJ, setErroNomeCNPJ] = useState(false);
  const [nomeCliente, setNomeCliente] = useState('');
  const [erroNomeCliente, setErroNomeCliente] = useState(false);

  const nomeInputRef = useRef(null);
  const scrollViewRef = useRef(null);

  // DEBOUNCES - A trava final para evitar o loop do FinanceiroInput
  const timeoutEntrada = useRef(null);
  const timeoutDesconto = useRef(null);
  const timeoutFrete = useRef(null);

  const [equipamentosSelecionados, setEquipamentosSelecionados] = useState([null]);
  const [quantidades, setQuantidades] = useState(['1']);
  const [valoresCalculados, setValoresCalculados] = useState([0]);

  const [observacao, setObservacao] = useState('')
  const [observacaoOrcamento, setObservacaoOrcamento] = useState([])

  const [pagamento, setPagamento] = useState("Boleto");
  const [localizacao, setLocalizacao] = useState("SP");
  const [faturamento, setFaturamento] = useState("CNPJ");
  const [condicao, setCondicao] = useState("Normal");

  const [parcelas, setParcelas] = useState(12);
  const [entrada, setEntrada] = useState(0);
  const [desconto, setDesconto] = useState(0);
  const [frete, setFrete] = useState(0);

  const [baseNF, setBaseNF] = useState(0);
  const [descFiscal, setDescFiscal] = useState(0);
  const [valorParcela, setValorParcela] = useState(0);
  const [servicoNF, setServicoNF] = useState(0);
  const [produtoNF, setProdutoNF] = useState(0);
  const [valorTotal, setValorTotal] = useState(0);
  const [valorParcelado, setValorParcelado] = useState(0);
  const [ultimaParcela, setUltimaParcela] = useState(0);

  // Estados de Controle de Edição
  const [registroId, setRegistroId] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [vendedorBloqueado, setVendedorBloqueado] = useState(false);

  const params = useLocalSearchParams();
  const isEditMode = !!params?.payload; // Verifica se existe payload

  const prefillRef = useRef(null);
  const prefillValoresRef = useRef({ entrada: null, parcelas: null });

  // Injeção do nome do vendedor do sistema Django
  useEffect(() => {
    console.log('[DEBUG] Iniciando verificação de USER_NAME');
    
    // Tenta capturar imediatamente
    if (typeof window !== 'undefined' && window.USER_NAME) {
      console.log('[DEBUG] USER_NAME encontrado de primeira:', window.USER_NAME);
      setNomeVendedor(window.USER_NAME);
      setVendedorBloqueado(true);
      return;
    }

    // Se não achou, tenta monitorar por 3 segundos (caso o script do Django demore um pouco)
    const interval = setInterval(() => {
      if (typeof window !== 'undefined' && window.USER_NAME) {
        console.log('[DEBUG] USER_NAME encontrado via polling:', window.USER_NAME);
        setNomeVendedor(window.USER_NAME);
        setVendedorBloqueado(true);
        clearInterval(interval);
      }
    }, 500);

    const timeout = setTimeout(() => {
      clearInterval(interval);
      console.log('[DEBUG] USER_NAME não foi encontrado após 3 segundos.');
    }, 3000);

    return () => { clearInterval(interval); clearTimeout(timeout); };
  }, []);

  function safeDecodePayload(p) {
    try {
      const jsonStr = decodeURIComponent(atob(String(p)));
      return JSON.parse(jsonStr);
    } catch (e) {
      return null;
    }
  }

  // 1) PEGA O PAYLOAD
  useEffect(() => {
    if (!params?.payload) return;
    const p = safeDecodePayload(params.payload);
    if (!p) return;

    prefillRef.current = p;

    // Resgata o ID do orçamento se ele for enviado
    const reqId = p.id || p.registro_id || p.pk;
    if (reqId) setRegistroId(reqId);

    if (p.nomeCliente !== undefined) setNomeCliente(p.nomeCliente || "");
    if (p.nomeVendedor !== undefined) setNomeVendedor(p.nomeVendedor || "");
    
    // Tenta diferentes chaves possíveis para o documento, blindando contra erros
    const docRaw = String(p.documento || p.document || p.cnpj || p.cpf || p.nomeCNPJ || p.nomeCnpj || "");
    const faturamentoPayload = String(p.faturamento || faturamento).toUpperCase();
    if (p.faturamento !== undefined) setFaturamento(faturamentoPayload); 

    const docDigits = docRaw.replace(/\D/g, "");
    if (docDigits) {
      const formatted = (faturamentoPayload === "CPF" ? formatCPF(docDigits) : formatCNPJ(docDigits));
      setNomeCNPJ(formatted);
    }
    
    if (p.localizacao !== undefined) setLocalizacao(p.localizacao || "SP");
    if (p.pagamento !== undefined) setPagamento(p.pagamento || "Boleto"); 

    if (p.parcelas !== undefined && p.parcelas !== null) {
      prefillValoresRef.current.parcelas = Number(p.parcelas) || 1;
      setParcelas(Number(p.parcelas) || 1);
    }
    if (p.entrada !== undefined && p.entrada !== null) {
      const entParsed = parseSafeNumber(p.entrada);
      prefillValoresRef.current.entrada = entParsed;
      setEntrada(entParsed);
    }

    if (p.desconto !== undefined) setDesconto(parseSafeNumber(p.desconto));
    if (p.frete !== undefined) setFrete(parseSafeNumber(p.frete));
    if (p.observacao !== undefined) setObservacao(p.observacao || "");

  }, [params?.payload]);

  // 2) PEGA EQUIPAMENTOS DO PAYLOAD
  useEffect(() => {
    if (!prefillRef.current) return;
    if (!Array.isArray(equipamentos) || equipamentos.length === 0) return;

    const p = prefillRef.current;
    const itens = Array.isArray(p.equipamentos) ? p.equipamentos : [];
    if (itens.length === 0) { prefillRef.current = null; return; }

    const norm = (s) => String(s ?? "").trim().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    const selected = []; const qtys = []; const obs = []; const vals = [];

    for (const it of itens) {
      const idOuNome = typeof it === 'object' ? (it.id ?? it.equipamento_id ?? it.equipamentoId ?? it.equipamento ?? it.nome ?? null) : it;
      const qtd = typeof it === 'object' ? (it.qtd ?? it.quantidade ?? 1) : 1;

      let eq = null;
      const rawDigits = idOuNome ? String(idOuNome).replace(/\D/g, "") : "";
      
      if (rawDigits) eq = equipamentos.find((e) => String(e.id) === String(rawDigits));
      if (!eq && idOuNome) {
        const alvo = norm(idOuNome);
        eq = equipamentos.find((e) => norm(e.nome) === alvo) || equipamentos.find((e) => norm(e.nome).includes(alvo) || alvo.includes(norm(e.nome)));
      }

      if (eq) {
        selected.push(eq); qtys.push(String(qtd || 1)); obs.push(''); vals.push(0);
      }
    }

    if (selected.length > 0) {
      setEquipamentosSelecionados(selected);
      setQuantidades(qtys);
      setObservacaoOrcamento(obs);
      setValoresCalculados(vals);
    }
    prefillRef.current = null;
  }, [equipamentos]);

  const tabelaTaxasCartao = {
    1: 0.0333, 2: 0.0438, 3: 0.0509, 4: 0.058, 5: 0.0652, 6: 0.0725,
    7: 0.0837, 8: 0.0912, 9: 0.0989, 10: 0.1067, 11: 0.1146, 12: 0.1250,
    13: 0.1307, 14: 0.139, 15: 0.1473, 16: 0.1558, 17: 0.1644, 18: 0.1732,
    19: 0.1820, 20: 0.1910, 21: 0.2002
  };

  const formatarMoeda = (valor) => {
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(valor) || 0);
  };

  function formatCNPJ(value) {
    value = value.replace(/\D/g, '').slice(0, 14);
    if (value.length > 12) return value.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{0,2}).*/, '$1.$2.$3/$4-$5');
    if (value.length > 8) return value.replace(/^(\d{2})(\d{3})(\d{3})(\d{0,4})/, '$1.$2.$3/$4');
    if (value.length > 5) return value.replace(/^(\d{2})(\d{3})(\d{0,3})/, '$1.$2.$3');
    if (value.length > 2) return value.replace(/^(\d{2})(\d{0,3})/, '$1.$2');
    return value;
  }

  function formatCPF(value) {
    value = value.replace(/\D/g, '').slice(0, 11);
    if (value.length > 9) return value.replace(/^(\d{3})(\d{3})(\d{3})(\d{0,2}).*/, '$1.$2.$3-$4');
    if (value.length > 6) return value.replace(/^(\d{3})(\d{3})(\d{0,3})/, '$1.$2.$3');
    if (value.length > 3) return value.replace(/^(\d{3})(\d{0,3})/, '$1.$2');
    return value;
  }

  var somaValores = useMemo(() => {
    return valoresCalculados.reduce((a, b) => a + (Number(b) || 0), 0);
  }, [valoresCalculados]);

  const pmt = (rate, nper, pv) => {
    const r = Number(rate) || 0;
    const n = Math.max(1, parseInt(nper, 10) || 1);
    const principal = Math.max(0, Number(pv) || 0);
    if (r === 0) return principal / n;
    return (principal * r) / (1 - Math.pow(1 + r, -n));
  };

  const valorAVistaEquip = useMemo(() => {
    return equipamentosSelecionados.reduce((sum, eq, idx) => {
      if (!eq) return sum;
      const q = parseInt(quantidades[idx], 10) || 0;
      let base = localizacao === 'SP' ? (eq.custo_geral || 0) : faturamento === 'CPF' ? (eq.custo_cpf || 0) : (eq.custo_cnpj || 0);
      return sum + (base * q);
    }, 0);
  }, [equipamentosSelecionados, quantidades, localizacao, faturamento]);

  const validarNomeCNPJ = () => {
    const nomeValido = nomeCNPJ.trim() !== '';
    const somenteNumeros = nomeCNPJ.replace(/\D/g, '');
    let valido = false;
    if (faturamento === 'CPF') valido = somenteNumeros.length === 11;
    else if (faturamento === 'CNPJ') valido = somenteNumeros.length === 14;
    else valido = nomeCNPJ.trim() !== '';

    setErroNomeCNPJ(!valido || !nomeValido)
    if (!nomeValido || !valido) {
      if (Platform.OS === 'web') {
        const inputElement = document.getElementById('nomeCNPJInput');
        if (inputElement) { inputElement.scrollIntoView({ behavior: 'smooth', block: 'center' }); inputElement.focus(); }
      } else { scrollViewRef.current?.scrollTo({ y: 0, animated: true }); }
      return false;
    }
    return true;
  };
  
  const validarNomeVendedor = () => {
    const nomeValido = nomeVendedor.trim() !== '';
    setErroNomeVendedor(!nomeValido);
    if (!nomeValido) {
      if (Platform.OS === 'web') {
        const inputElement = document.getElementById('nomeVendedorInput');
        if (inputElement) { inputElement.scrollIntoView({ behavior: 'smooth', block: 'center' }); inputElement.focus(); }
      } else { scrollViewRef.current?.scrollTo({ y: 0, animated: true }); }
      return false;
    }
    return true;
  };

  const validarNomeCliente = () => {
    const nomeValido = nomeCliente.trim() !== '';
    setErroNomeCliente(!nomeValido);
    if (!nomeValido) {
      if (Platform.OS === 'web') {
        const inputElement = document.getElementById('nomeClienteInput');
        if (inputElement) { inputElement.scrollIntoView({ behavior: 'smooth', block: 'center' }); inputElement.focus(); }
      } else { scrollViewRef.current?.scrollTo({ y: 0, animated: true }); }
      return false;
    }
    return true;
  };

  useEffect(() => {
    const carregarDados = async () => {
      try {
        const [resEquipamentos, resGrupos, resMarcas] = await Promise.all([
          fetch(equipamentos_URL, { mode: 'cors', headers: { 'Authorization': 'Token e18d142d3d92e504d3ad0ebb37c04fd85f5c5f8d' } }),
          fetch(tipo_equipamento_URL, { mode: 'cors', headers: { 'Authorization': 'Token e18d142d3d92e504d3ad0ebb37c04fd85f5c5f8d' } }),
          fetch(marca_equipamento_URL, { mode: 'cors', headers: { 'Authorization': 'Token e18d142d3d92e504d3ad0ebb37c04fd85f5c5f8d' } })
        ]);
        setEquipamentos(((await resEquipamentos.json()) || []).filter(equip => equip.disponibilidade === true));
        setGrupos(await resGrupos.json() || []);
        setMarcas(await resMarcas.json() || []);
        setLoading(false);
      } catch (error) {
        console.error('Erro ao carregar dados:', error);
        setLoading(false);
      }
    };
    carregarDados();
  }, []);

  const handleSelectEquipamento = (index, equipamento, observacao) => {
    const novosEquipamentos = [...equipamentosSelecionados];
    novosEquipamentos[index] = equipamento;
    setEquipamentosSelecionados(novosEquipamentos);
  };

  function verificarGrupo(equipamento) {
    if (!equipamento) return false;
    const tipoSelecionado = grupos.find(g => g.id === equipamento.grupo)?.nome || 'N/A'
    return ["DIAGNÓSTICO", "IMOBILIZADOR"].some(tipo => tipoSelecionado.includes(tipo));
  }

  const handleDetalhesOrcamento = (index, detalhe, equipamento) => {
    const observacoesNovas = [...observacaoOrcamento];
    const grupoValido = equipamento ? verificarGrupo(equipamento) : false;
    const temDetalhe = detalhe && detalhe !== null;
    observacoesNovas[index] = ((temDetalhe || grupoValido) && detalhe !== 'excluir')
      ? `<h2 class="section-title" style='border-bottom: none; padding-bottom:0px; font-size:17px;'>Está incluso para o <strong>${equipamento?.nome || ''}</strong>:</h2>${temDetalhe ? `${detalhe}<br>` : ''}${grupoValido ? '2 anos de suporte' : ''}`
      : '';
    setObservacaoOrcamento(observacoesNovas);
  };

  const calcularValor = (equipamento, quantidade) => {
    if (!equipamento) return 0;
    const base = localizacao === 'SP' ? equipamento.custo_geral : faturamento === "CPF" ? equipamento.custo_cpf : equipamento.custo_cnpj;
    return Math.round((base || 0) * quantidade);
  };

  const handleValoresCalculados = (index, value) => {
    const novosValoresCalculados = [...valoresCalculados];
    novosValoresCalculados[index] = calcularValor(equipamentosSelecionados[index], Number(value) || 0);
    setValoresCalculados(novosValoresCalculados);
  };

  const handleQuantidadeChange = (index, value) => {
    const novasQuantidades = [...quantidades];
    novasQuantidades[index] = value;
    setQuantidades(novasQuantidades);
  };

  const adicionarEquipamento = () => {
    if (equipamentosSelecionados.includes(null) || equipamentosSelecionados.length >= equipamentos.length) return;
    setEquipamentosSelecionados([null, ...equipamentosSelecionados]);
    setQuantidades(['1', ...quantidades]);
    setValoresCalculados([0, ...valoresCalculados]);
    setObservacaoOrcamento(['', ...observacaoOrcamento]);
  };

  const removerEquipamento = (index) => {
    if (equipamentosSelecionados.length <= 1) return;
    const novos = [...equipamentosSelecionados]; novos.splice(index, 1); setEquipamentosSelecionados(novos);
    const nQtds = [...quantidades]; nQtds.splice(index, 1); setQuantidades(nQtds);
    const nVals = [...valoresCalculados]; nVals.splice(index, 1); setValoresCalculados(nVals);
    const nObs = [...observacaoOrcamento]; if (index < nObs.length) { nObs.splice(index, 1); setObservacaoOrcamento(nObs); }
  };

  const optionsPagamento = [
  { label: 'Boleto', value: 'Boleto' },
  { label: 'Cartão', value: 'Cartao' },
  { label: 'PIX', value: 'PIX' },
];
  const optionsLocalizacao = [{ label: 'SP / Outros estados sem Inscrição Estadual ', value: 'SP' }, { label: 'Outros estados / CNPJ com Inscrição Estadual', value: 'Outros' }];
  const optionsFaturamento = [{ label: 'CPF', value: 'CPF' }, { label: 'CNPJ', value: 'CNPJ' }];

  useEffect(() => {
    let total = somaValores + (Number(frete) || 0);
    if (condicao !== 'Normal') total = equipamentosSelecionados.reduce((sum, eq) => sum + (eq?.custo_geral || 0), 0);
    setBaseNF(prev => prev !== total ? total : prev);
  }, [somaValores, frete, condicao, equipamentosSelecionados]);

  useEffect(() => {
    const percentual = localizacao === 'SP' ? 0.15 : 0.1;
    const total = Math.round((somaValores - baseNF) * percentual);
    setDescFiscal(prev => prev !== total ? total : prev);
  }, [localizacao, baseNF, somaValores]);

  // =========================
  // DEFAULTS: AUTO ENTRADA
  // =========================
  useEffect(() => {
    if (prefillValoresRef.current?.entrada !== null) {
       setEntrada(Math.round(Number(prefillValoresRef.current.entrada)));
       prefillValoresRef.current.entrada = null; 
       return;
    }

    let defaultEntrada = 0;
    if (pagamento === "Boleto") {
      if (localizacao === "SP") defaultEntrada = equipamentosSelecionados.reduce((sum, eq, idx) => eq?.entrada_sp_cnpj ? sum + (eq.entrada_sp_cnpj * (parseInt(quantidades[idx], 10) || 1)) : sum, 0);
      else if (faturamento === "CNPJ") defaultEntrada = equipamentosSelecionados.reduce((sum, eq, idx) => eq?.entrada_outros_cnpj ? sum + (eq.entrada_outros_cnpj * (parseInt(quantidades[idx], 10) || 1)) : sum, 0);
      else defaultEntrada = equipamentosSelecionados.reduce((sum, eq, idx) => eq?.entrada_outros_cpf ? sum + (eq.entrada_outros_cpf * (parseInt(quantidades[idx], 10) || 1)) : sum, 0);
    } 
    const newVal = Math.round(defaultEntrada);
    setEntrada(prev => prev !== newVal ? newVal : prev);
  }, [localizacao, pagamento, faturamento, equipamentosSelecionados, quantidades]);

  const [boletoDisponivel, setBoletoDisponivel] = useState(true);
  const [parcelasDesabilitadas, setParcelasDesabilitadas] = useState(false);

  useEffect(() => {
    const validos = equipamentosSelecionados.filter(e => e != null);
    if (validos.length === 0) {
      setBoletoDisponivel(prev => prev !== true ? true : prev);
      setParcelasDesabilitadas(prev => prev !== false ? false : prev);
      return;
    }

    const algumAceitaBoleto = validos.some(equip => equip.boleto);
    setBoletoDisponivel(prev => prev !== algumAceitaBoleto ? algumAceitaBoleto : prev);

    if (!algumAceitaBoleto && pagamento === "Boleto") {
      setPagamento("Cartao");
      setEntrada(prev => prev !== 0 ? 0 : prev);
    }

    const todosSaoAVista = validos.every(equip => equip.avista);
    setParcelasDesabilitadas(prev => prev !== todosSaoAVista ? todosSaoAVista : prev);

    if (todosSaoAVista && prefillValoresRef.current?.parcelas === null) {
      setParcelas(prev => Number(prev) !== 1 ? 1 : prev);
    }
  }, [equipamentosSelecionados, pagamento]);

  // =========================
  // DEFAULTS: AUTO PARCELAS
  // =========================
  useEffect(() => {
    // PIX: trava sempre em 1
    if (pagamento === "PIX") {
      setParcelas(prev => (Number(prev) !== 1 ? 1 : prev));
      setEntrada(prev => (Number(prev) !== 0 ? 0 : prev));
      return;
    }

    if (prefillValoresRef.current?.parcelas !== null) {
      setParcelas(prefillValoresRef.current.parcelas);
      prefillValoresRef.current.parcelas = null;
      return;
    }

    if (!parcelasDesabilitadas) {
      let maxParcelas = 12;
      const validEquipments = equipamentosSelecionados.filter(e => e != null);

      if (validEquipments.length > 0) {
        maxParcelas = Math.max(...validEquipments.map(equip => equip.parcelas || 12));
      }

      if (pagamento === "Cartao") maxParcelas = 12;

      setParcelas(prev => (Number(prev) !== maxParcelas ? maxParcelas : prev));
    } else {
      setParcelas(prev => (Number(prev) !== 1 ? 1 : prev));
    }
  }, [equipamentosSelecionados, pagamento, parcelasDesabilitadas]);

  useEffect(() => {
    const n = Math.max(1, parseInt(parcelas, 10) || 1);
    const toCent = (v) => Math.round((Number(v) || 0) * 100);
    const fromCent = (c) => (Number(c) || 0) / 100;

    const entradaNum = Number(entrada) || 0;
    const descontoNum = Number(desconto) || 0;
    const freteNum = Number(frete) || 0;

    let parcelaExib = 0; let totalPagoCent = 0;

    if (pagamento === 'Boleto') {
      const entradaEfetiva = entradaNum + freteNum;
      const baseFinanciavel = Math.max(0, (Number(valorAVistaEquip) || 0) - descontoNum);
      const pv = Math.max(0, baseFinanciavel - entradaNum);
      const rate = n < 3 ? 0.05 : taxa;
      const parcelaReal = pmt(rate, n, pv);

      const parcelaCent = Math.round(toCent(parcelaReal * n) / n);
      parcelaExib = fromCent(parcelaCent);
      totalPagoCent = toCent(entradaEfetiva) + (parcelaCent * n);

    } else if (pagamento === 'PIX') {
      // PIX = sem taxa, sempre 1x
      const total = Math.max(0, (Number(valorAVistaEquip) || 0) - descontoNum - entradaNum + freteNum);
      parcelaExib = total;              // como é 1x, parcela = total
      totalPagoCent = toCent(total);    // total pago

    } else {
      // Cartão
      const somaBaseTotal = Number(valorAVistaEquip) || 0;
      const taxaCartao = tabelaTaxasCartao[n] ?? 0;
      const pvSemTaxa = Math.max(0, (somaBaseTotal - descontoNum - entradaNum) + freteNum);
      const totalParcelas = (taxaCartao > 0) ? (pvSemTaxa / (1 - taxaCartao)) : pvSemTaxa;

      const parcelaCent = Math.round(toCent(totalParcelas) / n);
      parcelaExib = fromCent(parcelaCent);
      totalPagoCent = toCent(entradaNum) + (parcelaCent * n);
    }

    setValorParcela(prev => Number(prev) !== parcelaExib ? parcelaExib : prev);
    setUltimaParcela(prev => Number(prev) !== parcelaExib ? parcelaExib : prev);
    setValorParcelado(prev => Number(prev) !== fromCent(totalPagoCent) ? fromCent(totalPagoCent) : prev);
  }, [pagamento, parcelas, entrada, valorAVistaEquip, desconto, frete]);

  useEffect(() => {
    const newVal = parseInt(entrada ? entrada : 0) + (parcelas * valorParcela) - produtoNF;
    setServicoNF(prev => Number(prev) !== newVal ? newVal : prev);
  }, [entrada, parcelas, valorParcela, produtoNF]);

  useEffect(() => {
    const newVal = (pagamento === 'Boleto' && condicao === 'Normal') ? (parseInt(entrada ? entrada : 0) + (valorParcela * parcelas) + (Number(frete) || 0)) : baseNF;
    setProdutoNF(prev => Number(prev) !== newVal ? newVal : prev);
  }, [condicao, pagamento, entrada, parcelas, valorParcela, baseNF, frete]);

  useEffect(() => {
    const newVal = somaValores - descFiscal + (Number(frete) || 0);
    setValorTotal(prev => Number(prev) !== newVal ? newVal : prev);
  }, [somaValores, descFiscal, frete]);

  const calcularValorProdutoAVistaFinal = (equipamento, quantidade) => {
    if (!equipamento) return 0;

    const q = parseInt(quantidade, 10) || 0;

    let valorBase = 0;
    if (localizacao === 'SP') {
      valorBase = (equipamento.custo_geral || 0) * q;
    } else if (faturamento === 'CPF') {
      valorBase = (equipamento.custo_cpf || 0) * q;
    } else {
      valorBase = (equipamento.custo_cnpj || 0) * q;
    }

    const totalBase = Number(valorAVistaEquip) || 0;
    const proporcao = totalBase > 0 ? (valorBase / totalBase) : 0;

    const descontoItem = (Number(desconto) || 0) * proporcao;
    const freteItem = (Number(frete) || 0) * proporcao;

    // regra do PIX / à vista
    return Math.round((valorBase - descontoItem + freteItem) * 100) / 100;
  };

  const calcularValorProdutoFinal = (equipamento, quantidade) => {
    if (!equipamento) return 0;
    let valorBase = localizacao === 'SP' ? (equipamento.custo_geral || 0) * quantidade : (faturamento === 'CPF' ? (equipamento.custo_cpf || 0) * quantidade : (equipamento.custo_cnpj || 0) * quantidade);
    const somaBaseTotal = valorAVistaEquip - (Number(desconto) || 0);
    const proporcao = (somaBaseTotal > 0) ? (valorBase / somaBaseTotal) : 0;
    const descontoItem = (Number(desconto) || 0) * proporcao;
    const entradaItem = (Number(entrada) || 0) * proporcao;
    const financiadoItem = Math.max(0, valorBase - descontoItem - entradaItem);

    if (pagamento === 'Boleto') {
      const rate = (parcelas < 3) ? 0.05 : taxa; 
      if (financiadoItem === 0) return Math.round(valorBase - descontoItem);
      return Math.round(entradaItem + pmt(rate, parcelas, financiadoItem) * parcelas);
    }

    if (pagamento === 'PIX') {
      // PIX = sem taxa
      return Math.round(valorBase - descontoItem);
    }

    const taxaCartao = tabelaTaxasCartao[parcelas] ?? 0;
    if (!taxaCartao || financiadoItem === 0) return Math.round(valorBase - descontoItem);
    return Math.round(entradaItem + financiadoItem + (financiadoItem * (taxaCartao / (1 - taxaCartao))));
  };

  useEffect(() => {
    const novosValores = equipamentosSelecionados.map((equipamento, index) => {
      if (!equipamento) return 0;
      const quantidade = parseInt(quantidades[index], 10) || 0;
      return calcularValorProdutoFinal(equipamento, quantidade);
    });
    setValoresCalculados(prev => {
      const isDifferent = prev.length !== novosValores.length || prev.some((v, idx) => Number(v) !== Number(novosValores[idx]));
      return isDifferent ? novosValores : prev;
    });
  }, [faturamento, localizacao, equipamentosSelecionados, quantidades, pagamento, parcelas, entrada, desconto, frete, valorAVistaEquip]);

  // Busca automática de cliente por CPF/CNPJ
  useEffect(() => {
    const buscarCliente = async () => {
      const docLimpo = nomeCNPJ.replace(/\D/g, '');
      
      // Só busca se for CPF (11) ou CNPJ (14) completo
      if (docLimpo.length === 11 || docLimpo.length === 14) {
        try {
          const response = await fetch(`${API_BASE_URL}/clientes/cpf_cnpj=${docLimpo}`, {
            method: 'GET',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Token e18d142d3d92e504d3ad0ebb37c04fd85f5c5f8d'
            }
          });
          if (response.ok) {
            const jsonResponse = await response.json(); // Chamei de jsonResponse para não confundir com a chave 'data'
            // console.log('Resposta da API de cliente:', jsonResponse);

            if (jsonResponse.ok && jsonResponse.data) {
              // Se encontrou o cliente, o objeto está dentro de .data
              const cliente = jsonResponse.data;

              if (cliente.nomeCliente) {
                  setNomeCliente(cliente.nomeCliente);
              } else if (cliente.nome) {
                  setNomeCliente(cliente.nome);
              }

              // Dica: Se quiser preencher o telefone e o documento também:
              // if (cliente.telefone) setTelefone(cliente.telefone);
              // if (cliente.documento) setDocumento(cliente.documento);
                  
            } else {
              console.log('Cliente não encontrado ou erro na resposta');
            }
          }
        } catch (err) {
          console.error('Erro ao buscar cliente:', err);
        }
      }
    };

    const timeoutId = setTimeout(buscarCliente, 500); // Debounce de 500ms
    return () => clearTimeout(timeoutId);
  }, [nomeCNPJ]);

  const equipamentosValidos = equipamentosSelecionados.filter(e => e != null);

  const itensPDF = equipamentosValidos.map((equip, index) => {
    const quantidade = parseInt(quantidades[index], 10) || 1;

    // valor base real do equipamento no banco (sem taxa)
    const valorBaseUnitario =
      localizacao === 'SP'
        ? (equip.custo_geral || 0)
        : faturamento === 'CPF'
          ? (equip.custo_cpf || 0)
          : (equip.custo_cnpj || 0);

    const valorBaseTotal = Math.round((valorBaseUnitario * quantidade) * 100) / 100;

    // valor com taxa / financiamento / cálculo atual do simulador
    const valorComTaxaTotal = Math.round((Number(valoresCalculados[index]) || 0) * 100) / 100;
    const valorComTaxaUnitario =
      quantidade > 0
        ? Math.round((valorComTaxaTotal / quantidade) * 100) / 100
        : 0;

    // valor à vista calculado com a mesma lógica do PIX
    const valorAvistaTotal = calcularValorProdutoAVistaFinal(equip, quantidade);
    const valorAvistaUnitario =
      quantidade > 0
        ? Math.round((valorAvistaTotal / quantidade) * 100) / 100
        : 0;

    return {
      nome: equip.nome,
      quantidade,

      // valores normais / taxados
      valorUnitario: valorComTaxaUnitario,
      valorTotal: valorComTaxaTotal,

      // valores base do banco (sem taxa)
      valorBaseUnitario: Math.round(valorBaseUnitario * 100) / 100,
      valorBaseTotal: valorBaseTotal,

      // valores calculados para à vista (mesma lógica do PIX)
      valorAvistaUnitario: valorAvistaUnitario,
      valorAvistaTotal: valorAvistaTotal,
    };
  });

  // Funções de Roteamento e Edição (Novas)
  const handleVoltarPainel = () => {
    if (Platform.OS === 'web') {
      const termoBusca = nomeCNPJ || nomeCliente;
      
      // Cria um "payload" invisível
      const voltarPayload = {
        registroId: registroId,
        q: termoBusca
      };
      
      // Salva na memória curta do navegador
      sessionStorage.setItem('voltarParaPedido', JSON.stringify(voltarPayload));

      // Vai para a URL 100% limpa!
      window.location.href = '/pedido/'; 
    } else {
      router.replace('/pedido'); 
    }
  };

  const handleSalvarAlteracoes = async () => {
    if (!validarNomeCliente() || !validarNomeVendedor() || !validarNomeCNPJ()) return;
    
    setIsSaving(true);
    
    const payload = {
      equipamentos: equipamentosSelecionados.map(e => e?.id).filter(Boolean),
      quantidades,
      usarPrecosCliente: true,
      itensPDF,
      subtotalEquipamentosExibicao: pagamento === 'Cartao' ? valorParcelado : somaValores,
      valorTotal: pagamento === 'Cartao' ? valorParcelado : somaValores,
      entrada,
      parcelas,
      localizacao,
      faturamento,
      valorParcela,
      desconto,
      frete,
      observacao,
      descricao: observacaoOrcamento,
      tipoPagamento: pagamento,
      nomeVendedor,
      nomeCliente,
      nomeCNPJ,
    };

    try {
      const targetUrl = registroId 
        ? `${API_BASE_URL}/registros/${registroId}/atualizar/` 
        : `${API_BASE_URL}/generate-pdf/`;

      // Se não tem id, mandamos pro generate normal apenas como fallback de salvamento
      if (!registroId) {
        alert("Atenção: Este orçamento não possuía um ID atrelado. Ele será gerado como um novo registro no banco.");
      }

      const response = await fetch(targetUrl, {
        method: registroId ? 'PUT' : 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Token e18d142d3d92e504d3ad0ebb37c04fd85f5c5f8d'
        },
        body: JSON.stringify(payload)
      });
      
      if (response.ok) {
        alert('Alterações salvas com sucesso!');
        // Se quiser que ele volte ao salvar, descomente a linha abaixo:
        // handleVoltarPainel();
      } else {
        alert('Erro ao salvar as alterações no banco de dados.');
      }
    } catch (err) {
      console.error('Erro na atualização:', err);
      alert('Erro de conexão ao tentar salvar.');
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.container}>
      <ScrollView ref={scrollViewRef} contentContainerStyle={styles.contentContainer} keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive" showsVerticalScrollIndicator={false} nestedScrollEnabled={true}>
        {loading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#4A90E2" />
            <Text style={styles.loadingText}>Carregando dados...</Text>
          </View>
        ) : (
          <>
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Configurações</Text>
              <View style={styles.inputGroup} id='nomeVendedorInput'>
                <Text style={styles.radioGroupTitle}>Nome do vendedor *</Text>
                <TextInput
                  ref={nomeInputRef}
                  style={[styles.input, { padding: 12, backgroundColor: vendedorBloqueado ? '#f1f1f1' : 'rgb(248, 249, 250)', borderColor: erroNomeVendedor ? '#E74C3C' : '#E9ECEF', borderWidth: 2, borderRadius: 8, color: vendedorBloqueado ? '#7f8c8d' : '#000' }]}
                  placeholder="Digite o nome do vendedor"
                  placeholderTextColor="#95a5a6"
                  value={nomeVendedor}
                  editable={!vendedorBloqueado}
                  onChangeText={(text) => { setNomeVendedor(text); if (text.trim() !== '') setErroNomeVendedor(false); }}
                />
                {erroNomeVendedor && <Text style={styles.errorText}>⚠️ O nome do vendedor é obrigatório para gerar o PDF.</Text>}
              </View>
              <View style={styles.inputGroup} id='nomeClienteInput'>
                <Text style={styles.radioGroupTitle}>Nome do cliente *</Text>
                <TextInput
                  ref={nomeInputRef}
                  style={[styles.input, { padding: 12, backgroundColor: 'rgb(248, 249, 250)', borderColor: erroNomeCliente ? '#E74C3C' : '#E9ECEF', borderWidth: 2, borderRadius: 8 }]}
                  placeholder="Digite o nome do cliente"
                  placeholderTextColor="#95a5a6"
                  value={nomeCliente}
                  onChangeText={(text) => { setNomeCliente(text); if (text.trim() !== '') setErroNomeCliente(false); }}
                />
                {erroNomeCliente && <Text style={styles.errorText}>⚠️ O nome do cliente é obrigatório.</Text>}
              </View>

              <View style={styles.radioGroup}>
                <Text style={styles.radioGroupTitle}>Forma de Pagamento</Text>
                <Radio
                  options={boletoDisponivel ? optionsPagamento : optionsPagamento.filter(opt => opt.value !== 'Boleto')}
                  checkedValue={pagamento}
                  onChange={setPagamento}
                  containerStyle={styles.radioContainer}
                />
              </View>

              <View style={styles.radioGroup}>
                <Text style={styles.radioGroupTitle}>Localização</Text>
                <Radio options={optionsLocalizacao} checkedValue={localizacao} onChange={setLocalizacao} containerStyle={styles.radioContainer} />
              </View>

              <View style={styles.radioGroup}>
                <Text style={styles.radioGroupTitle}>Faturamento</Text>
                <Radio 
                  options={optionsFaturamento} 
                  checkedValue={faturamento} 
                  onChange={(val) => {
                    setFaturamento(val);
                    setNomeCNPJ(''); // Limpa SOMENTE quando o usuário clica!
                  }} 
                  containerStyle={styles.radioContainer} 
                />
                <View style={styles.inputGroup} id='nomeCNPJInput'>
                  <Text style={styles.radioGroupTitle}>{faturamento === "CNPJ" ? 'CNPJ do cliente' : 'CPF do cliente'}</Text>
                  <TextInput
                    keyboardType="numeric"
                    ref={nomeInputRef}
                    style={[styles.input, { padding: 12, backgroundColor: 'rgb(248, 249, 250)', borderColor: erroNomeCNPJ ? '#E74C3C' : '#E9ECEF', borderWidth: 2, borderRadius: 8 }]}
                    placeholder={faturamento === "CNPJ" ? 'Digite o CNPJ do cliente' : 'Digite o CPF do cliente'}
                    placeholderTextColor="#95a5a6"
                    value={nomeCNPJ}
                    onChangeText={(text) => {
                      const formatted = (faturamento === "CNPJ" ? formatCNPJ(text) : formatCPF(text))
                      setNomeCNPJ(formatted);
                      if (formatted.trim() !== '') setErroNomeCNPJ(false);
                    }}
                  />
                  {erroNomeCNPJ && <Text style={styles.errorText}>{faturamento === "CNPJ" ? '⚠️ O CNPJ do cliente inválido.' : '⚠️ O CPF do cliente inválido.'}</Text>}
                </View>
              </View>
            </View>

            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>Equipamentos</Text>
                <TouchableOpacity style={[styles.addButton, equipamentosSelecionados.length >= equipamentos.length && styles.disabledButton]} onPress={adicionarEquipamento} disabled={equipamentosSelecionados.length >= equipamentos.length}>
                  <Text style={styles.buttonText}>＋</Text>
                </TouchableOpacity>
              </View>

              {equipamentosSelecionados.map((equipamento, index) => (
                <View key={`equip-${index}`} style={styles.card}>
                  <View style={styles.cardHeader}>
                    <Text style={styles.cardTitle}>Equipamento #{index + 1}</Text>
                    {equipamentosSelecionados.length > 1 && (
                      <TouchableOpacity style={styles.removeButton} onPress={() => { removerEquipamento(index); handleDetalhesOrcamento(index, 'excluir', equipamento) }}>
                        <Text style={styles.buttonTextRemove}>X</Text>
                      </TouchableOpacity>
                    )}
                  </View>
                  
                  <EquipamentoSelector
                    equipamentos={equipamentos}
                    marcas={marcas}
                    selectedEquipamento={equipamento}
                    onSelect={(equip) => { handleSelectEquipamento(index, equip); handleDetalhesOrcamento(index, localizacao === "SP" ? equip?.detalhes_sp_html : equip?.detalhes_html, equip); }}
                    disabledEquipamentos={equipamentosSelecionados.filter(e => e)}
                  />

                  {equipamento && (
                    <View style={styles.cardBody}>
                      <View style={styles.inputRow}>
                        <Text style={styles.inputLabel}>Quantidade:</Text>
                        <NumericInput value={quantidades[index]} onValueChange={(value) => { handleQuantidadeChange(index, value); handleValoresCalculados(index, value); }} style={styles.input} />
                      </View>
                      <View style={styles.valueRow}>
                        <Text style={styles.valueLabel}>Valor Unitário:</Text>
                        <Text style={styles.valueText}>{localizacao === 'SP' ? formatarMoeda(equipamento.custo_geral) : faturamento === 'CPF' ? formatarMoeda(equipamento.custo_cpf) : formatarMoeda(equipamento.custo_cnpj)}</Text>
                      </View>
                      <View style={styles.valueRow}>
                        <Text style={styles.valueLabel}>Valor Total:</Text>
                        <Text style={[styles.valueText, styles.boldText]}>{formatarMoeda(valoresCalculados[index] || 0)}</Text>
                      </View>
                    </View>
                  )}
                </View>
              ))}

              <View style={styles.summaryCard}>
                <Text style={styles.summaryTitle}>Valor Total dos Equipamentos</Text>
                <Text style={styles.summaryValue}>{formatarMoeda(somaValores)}</Text>
              </View>
            </View>

            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Parâmetros Financeiros</Text>
              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>Entrada</Text>
                <FinanceiroInput
                  value={entrada}
                  onValueChange={(val) => {
                    const num = parseSafeNumber(val);
                    if (timeoutEntrada.current) clearTimeout(timeoutEntrada.current);
                    timeoutEntrada.current = setTimeout(() => { setEntrada(prev => prev !== num ? num : prev); }, 400);
                  }}
                  style={styles.input}
                  tipoValor={'numero'}
                />
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>Parcelas</Text>
                <NumericInput
                  value={parcelas}
                  onValueChange={(val) => {
                    const num = Number(val) || 1;
                    setParcelas(prev => prev !== num ? num : prev); 
                  }}
                  style={styles.input}
                  min={1} max={21} disabled={parcelasDesabilitadas || pagamento === "PIX"}
                />
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>Desconto</Text>
                <FinanceiroInput
                  value={desconto}
                  onValueChange={(val) => {
                    const num = parseSafeNumber(val);
                    if (timeoutDesconto.current) clearTimeout(timeoutDesconto.current);
                    timeoutDesconto.current = setTimeout(() => { setDesconto(prev => prev !== num ? num : prev); }, 400);
                  }}
                  style={styles.input} valorTotal={somaValores}
                />
              </View>
              
              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>Frete</Text>
                <FinanceiroInput
                  value={frete}
                  onValueChange={(val) => {
                    const num = parseSafeNumber(val);
                    if (timeoutFrete.current) clearTimeout(timeoutFrete.current);
                    timeoutFrete.current = setTimeout(() => { setFrete(prev => prev !== num ? num : prev); }, 400);
                  }}
                  style={styles.input} tipoValor={'numero'}
                />
              </View>
            </View>

            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Resultados</Text>
              <View style={styles.resultCard}>
                <View style={styles.resultRow}>
                  <Text style={styles.resultLabel}>{parcelas}x Valor da Parcela:</Text>
                  <Text style={styles.resultValue}>{formatarMoeda(valorParcela)}</Text>
                </View>
                <View style={styles.divider} />
                <View style={styles.resultRow}>
                  <Text style={[styles.resultLabel, styles.boldText]}>À Vista:</Text>
                  <Text style={[styles.resultValue, styles.boldText]}>{formatarMoeda(Math.max(0, (Number(valorAVistaEquip)||0) - (Number(desconto)||0) + (Number(frete)||0)))}</Text>
                </View>
                <View style={styles.resultRow}>
                  <Text style={[styles.resultLabel, styles.boldText]}>Total {parcelas}x:</Text>
                  <Text style={[styles.resultValue, styles.boldText, styles.primaryText]}>{formatarMoeda(valorParcelado)}</Text>
                </View>
              </View>
            </View>
            
            <View style={styles.section}>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>Observações:</Text>
              </View>
              <View style={styles.card}>
                <TextInput placeholder="Adicione observações para o cliente..." placeholderTextColor="#95a5a6" autoCapitalize="none" multiline={true} onChangeText={setObservacao} value={observacao} />
              </View>
            </View>
          </>
        )}

        {equipamentosValidos.length > 0 && (
          <View style={styles.actionsWrapper}>
            
            {/* BOTÃO EXISTENTE DE GERAR PDF */}
            <PDFSimulacao
              itensPDF={itensPDF}
              subtotalEquipamentosExibicao={pagamento === 'Cartao' ? valorParcelado : somaValores}
              valorTotal={pagamento === 'Cartao' ? valorParcelado : somaValores}
              entrada={entrada} equipamentos={equipamentosValidos} parcelas={parcelas}
              localizacao={localizacao} faturamento={faturamento} quantidades={quantidades}
              valorParcela={valorParcela} ultimaParcela={ultimaParcela}
              baseNF={baseNF} produtoNF={produtoNF} servicoNF={servicoNF}
              descFiscal={descFiscal} valorParcelado={valorParcelado}
              desconto={desconto} observacao={observacao} descricao={observacaoOrcamento}
              tipoPagamento={pagamento} nomeVendedor={nomeVendedor} nomeCliente={nomeCliente}
              validarNomeVendedor={validarNomeVendedor} nomeCNPJ={nomeCNPJ} validarNomeCNPJ={validarNomeCNPJ}
              validarNomeCliente={validarNomeCliente} frete={frete}
            />

            {/* BOTÕES NOVOS (Exibidos se acessou via Payload) */}
            {isEditMode && (
              <View style={styles.editButtonsContainer}>
                <TouchableOpacity 
                  style={[styles.saveButton, isSaving && styles.disabledButton]} 
                  onPress={handleSalvarAlteracoes}
                  disabled={isSaving}
                >
                  <Text style={styles.editButtonText}>
                    {isSaving ? 'Salvando...' : 'Salvar Alterações'}
                  </Text>
                </TouchableOpacity>

                <TouchableOpacity 
                  style={styles.backButton} 
                  onPress={handleVoltarPainel}
                  disabled={isSaving}
                >
                  <Text style={styles.editButtonText}>Voltar para Painel</Text>
                </TouchableOpacity>
              </View>
            )}

          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F5F7FA' },
  contentContainer: { padding: 16, paddingBottom: 48 },
  loadingContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20 },
  loadingText: { marginTop: 16, fontSize: 16, color: '#666' },
  header: { marginBottom: 24, paddingHorizontal: 8 },
  headerTitle: { fontSize: 28, fontWeight: 'bold', color: '#2C3E50', marginBottom: 4 },
  headerSubtitle: { fontSize: 16, color: '#7F8C8D' },
  section: { backgroundColor: 'white', borderRadius: 12, padding: 16, marginBottom: 16, shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.1, shadowRadius: 4, elevation: 2 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  sectionTitle: { fontSize: 20, fontWeight: '600', color: '#2C3E50' },
  addButton: { backgroundColor: '#3498DB', borderRadius: 20, width: 40, height: 40, justifyContent: 'center', alignItems: 'center', shadowColor: '#000', shadowOffset: { width: 0, height: 2 }, shadowOpacity: 0.2, shadowRadius: 4, elevation: 2 },
  disabledButton: { backgroundColor: '#BDC3C7', opacity: 0.7 },
  card: { backgroundColor: '#F8F9FA', borderRadius: 10, padding: 16, marginBottom: 12, borderWidth: 1, borderColor: '#E9ECEF' },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  cardTitle: { fontSize: 16, fontWeight: '600', color: '#495057' },
  removeButton: { backgroundColor: '#E74C3C', borderRadius: 15, width: 30, height: 30, justifyContent: 'center', alignItems: 'center' },
  cardBody: { marginTop: 12 },
  inputRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 8 },
  valueRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8 },
  inputLabel: { fontSize: 14, color: '#495057', marginRight: 12, width: 100 },
  valueLabel: { fontSize: 14, color: '#6C757D' },
  valueText: { fontSize: 14, color: '#495057' },
  boldText: { fontWeight: '600' },
  input: { flex: 1 },
  inputGroup: { marginBottom: 16 },
  radioGroup: { marginBottom: 16 },
  radioGroupTitle: { fontSize: 14, color: '#495057', marginBottom: 8, fontWeight: '500' },
  radioContainer: { flexDirection: 'row', justifyContent: 'space-between' },
  summaryCard: { backgroundColor: '#E3F2FD', borderRadius: 8, padding: 12, marginTop: 8, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  summaryTitle: { fontSize: 14, color: '#0D47A1', fontWeight: '500' },
  summaryValue: { fontSize: 16, color: '#0D47A1', fontWeight: 'bold' },
  resultCard: { backgroundColor: '#F8F9FA', borderRadius: 10, padding: 16 },
  resultRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 12 },
  resultLabel: { fontSize: 14, color: '#6C757D' },
  resultValue: { fontSize: 14, color: '#495057' },
  primaryText: { color: '#3498DB' },
  divider: { height: 1, backgroundColor: '#DEE2E6', marginVertical: 8 },
  buttonText: { color: 'white', fontSize: 20, fontWeight: 'bold' },
  buttonTextRemove: { color: 'white', fontSize: 14, fontWeight: 'bold' },
  errorText: { color: '#E74C3C', fontSize: 12, marginTop: 4, fontWeight: '500' },
  
  actionsWrapper: { marginTop: 8, gap: 12 },
  editButtonsContainer: { flexDirection: Platform.OS === 'web' ? 'row' : 'column', gap: 12, marginTop: 4 },
  saveButton: { flex: 1, backgroundColor: '#27ae60', padding: 16, borderRadius: 10, justifyContent: 'center', alignItems: 'center' },
  backButton: { flex: 1, backgroundColor: '#7f8c8d', padding: 16, borderRadius: 10, justifyContent: 'center', alignItems: 'center' },
  editButtonText: { color: '#fff', fontSize: 16, fontWeight: 'bold', textAlign: 'center' }
});