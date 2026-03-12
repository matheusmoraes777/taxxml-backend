import { useState, useEffect } from 'react'
import { CreditCard, QrCode, Download, Loader2, Users, BarChart3, ShieldCheck, LogOut, ArrowRight, UserPlus, Activity, DollarSign } from 'lucide-react'
import { auth, loginComGoogle, sairDaConta } from './firebase'
import { onAuthStateChanged } from 'firebase/auth'

const API_URL = 'https://taxxml-api.onrender.com'

function App() {
  const [usuario, setUsuario] = useState(null)
  const [isAdmin, setIsAdmin] = useState(false) 
  const [view, setView] = useState('login')
  const [loading, setLoading] = useState(false)
  const [keys, setKeys] = useState('')
  const [qrBase64, setQrBase64] = useState('')
  const [checkoutUrl, setCheckoutUrl] = useState('')
  const [payId, setPayId] = useState(null)
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [nome, setNome] = useState('')
  const [adminStats, setAdminStats] = useState({ total_xmls: 0, faturamento: 0, clientes_ativos: 0, atividades: [] })

  const validKeys = keys.split('\n').map(k => k.trim()).filter(k => k.length === 44)
  const total = validKeys.length
  const totalPrice = (total * 0.15).toFixed(2)

  useEffect(() => {
    onAuthStateChanged(auth, (user) => { if (user) { setUsuario(user); setView('customer'); } });
  }, []);

  useEffect(() => {
    if (isAdmin) {
      const fetchStats = async () => {
        try { const res = await fetch(`${API_URL}/api/admin/stats`); setAdminStats(await res.json()); } catch (e) {}
      };
      fetchStats();
    }
  }, [isAdmin]);

  const handlePagamento = async (tipo) => {
    if (total === 0) return alert("Cole as chaves primeiro!");
    setLoading(true); setQrBase64(''); setCheckoutUrl('');
    try {
      const res = await fetch(`${API_URL}/api/pagar-${tipo}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quantidade: total, email: usuario?.email || 'anonimo@taxxml.com' })
      });
      const data = await res.json();
      if (data.qr_code_base64) { setQrBase64(data.qr_code_base64); setPayId(data.payment_id); }
      else if (data.checkout_url) { setCheckoutUrl(data.checkout_url); }
      else { alert(data.erro || "Erro ao gerar pagamento"); }
    } catch (e) { alert("Erro de conexão com o servidor."); }
    setLoading(false);
  }

  if (view === 'login') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 p-6 font-sans">
        <div className="bg-white p-8 rounded-3xl shadow-xl w-full max-w-md border">
          <div className="flex justify-center mb-6"><img src="https://i.ibb.co/7x0Qyqr8/taxxml-logo.jpg" alt="Logo" className="w-64" /></div>
          <div className="space-y-4">
            <input type="email" placeholder="E-mail" value={email} onChange={e => setEmail(e.target.value)} className="w-full p-4 bg-slate-50 border rounded-xl" />
            <input type="password" placeholder="Senha" value={senha} onChange={e => setSenha(e.target.value)} className="w-full p-4 bg-slate-50 border rounded-xl" />
            <button onClick={() => { /* Função de login aqui */ }} className="w-full py-4 bg-slate-800 text-white font-bold rounded-xl">Entrar</button>
            <button onClick={() => loginComGoogle()} className="w-full py-3 border-2 rounded-xl font-bold flex justify-center items-center gap-3"><img src="https://img.icons8.com/color/24/google-logo.png" /> Google</button>
            <div className="flex justify-between pt-4"><button onClick={() => setView('register')} className="text-sky-600 font-bold">Criar Conta</button><button onClick={() => { const s = prompt("Senha:"); if(s==="123456Mat"){setIsAdmin(true); setView('admin');} }} className="text-slate-200"><ShieldCheck/></button></div>
          </div>
        </div>
      </div>
    )
  }

  if (view === 'customer') {
    return (
      <div className="min-h-screen bg-slate-50 p-8 font-sans">
        <div className="max-w-6xl mx-auto">
          <header className="flex justify-between items-center mb-10 bg-white p-6 rounded-2xl border shadow-sm">
            <h1 className="text-2xl font-black text-slate-800">Tax XML</h1>
            <div className="flex gap-3">
              {isAdmin && <button onClick={() => setView('admin')} className="px-4 py-2 bg-sky-100 text-sky-700 rounded-xl font-bold">Admin</button>}
              <button onClick={() => { sairDaConta(); setView('login'); }} className="px-4 py-2 bg-red-50 text-red-600 rounded-xl font-bold">Sair</button>
            </div>
          </header>
          <div className="grid lg:grid-cols-3 gap-8">
            <div className="lg:col-span-2 bg-white p-8 rounded-3xl border shadow-sm">
              <h2 className="text-xl font-bold mb-4 flex gap-2"><Download className="text-sky-500"/> 1. Chaves</h2>
              <textarea className="w-full h-72 p-5 bg-slate-50 border rounded-2xl font-mono text-sm" placeholder="Cole aqui..." value={keys} onChange={e => setKeys(e.target.value)} />
            </div>
            <div className="bg-white p-8 rounded-3xl border shadow-sm text-center">
              <h2 className="text-xl font-bold mb-6">2. Pagamento</h2>
              <div className="text-4xl font-black text-emerald-500 mb-6">R$ {totalPrice}</div>
              {loading ? <Loader2 className="animate-spin mx-auto w-10 h-10 text-sky-500" /> : (
                <>
                  {!qrBase64 && !checkoutUrl && (
                    <div className="space-y-3">
                      <button onClick={() => handlePagamento('pix')} className="w-full py-4 bg-emerald-500 text-white font-bold rounded-xl flex justify-center items-center gap-2"><QrCode/> Gerar PIX</button>
                      <button onClick={() => handlePagamento('cartao')} className="w-full py-4 bg-slate-800 text-white font-bold rounded-xl flex justify-center items-center gap-2"><CreditCard/> Cartão</button>
                    </div>
                  )}
                  {qrBase64 && <div className="space-y-4"><img src={`data:image/png;base64,${qrBase64}`} className="mx-auto border p-2 rounded-xl" /><p className="text-xs font-bold text-slate-500">Escaneie o QR Code acima</p></div>}
                  {checkoutUrl && <a href={checkoutUrl} target="_blank" className="block py-4 bg-sky-500 text-white font-bold rounded-xl">Abrir Checkout</a>}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (view === 'admin') {
     return (
      <div className="min-h-screen bg-[#0f172a] text-slate-300 p-8 flex flex-col items-center">
        <div className="w-full max-w-5xl flex justify-between items-center mb-8">
          <h1 className="text-3xl font-black text-white flex gap-3"><ShieldCheck className="text-sky-500"/> Painel Admin</h1>
          <button onClick={() => setView('customer')} className="bg-slate-800 px-6 py-2 rounded-xl font-bold">Voltar</button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full max-w-5xl">
            <div className="bg-[#1e293b] p-8 rounded-2xl border border-slate-800"><div className="text-slate-400 text-sm font-bold uppercase mb-2">Faturamento</div><div className="text-4xl font-black text-emerald-400">R$ {adminStats.faturamento.toFixed(2)}</div></div>
            <div className="bg-[#1e293b] p-8 rounded-2xl border border-slate-800"><div className="text-slate-400 text-sm font-bold uppercase mb-2">XMLs Totais</div><div className="text-4xl font-black text-white">{adminStats.total_xmls}</div></div>
            <div className="bg-[#1e293b] p-8 rounded-2xl border border-slate-800"><div className="text-slate-400 text-sm font-bold uppercase mb-2">Clientes</div><div className="text-4xl font-black text-white">{adminStats.clientes_ativos}</div></div>
        </div>
      </div>
    )
  }
  return null;
}
export default App;
