-- ============================================================
-- MIGRAÇÃO — Adiciona colunas e RLS às tabelas existentes
-- Execute este script no SQL Editor do Supabase.
-- ============================================================

-- 0. Extensões
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. CRIAR TABELAS NOVAS (só se não existirem)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.joint_accounts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nome        TEXT NOT NULL,
    invite_code TEXT UNIQUE NOT NULL DEFAULT substr(md5(random()::text), 1, 8),
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.profiles (
    id               UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name     TEXT NOT NULL DEFAULT '',
    avatar_url       TEXT DEFAULT '',
    joint_account_id UUID REFERENCES public.joint_accounts(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.categorias (
    id   SERIAL PRIMARY KEY,
    nome TEXT UNIQUE NOT NULL
);

INSERT INTO public.categorias (nome) VALUES
    ('Alimentação'), ('Transporte'), ('Lazer'), ('Moradia'),
    ('Saúde'), ('Educação'), ('Vestuário'), ('Assinaturas'),
    ('Presentes'), ('Outros')
ON CONFLICT (nome) DO NOTHING;

-- ============================================================
-- 2. MIGRAR TABELA: gastos
-- Adiciona colunas que faltam (ignora se já existem)
-- ============================================================

DO $$
BEGIN
    -- profile_id
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'gastos' AND column_name = 'profile_id'
    ) THEN
        ALTER TABLE public.gastos ADD COLUMN profile_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE;
    END IF;

    -- categoria
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'gastos' AND column_name = 'categoria'
    ) THEN
        ALTER TABLE public.gastos ADD COLUMN categoria TEXT NOT NULL DEFAULT 'Outros';
    END IF;

    -- shared
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'gastos' AND column_name = 'shared'
    ) THEN
        ALTER TABLE public.gastos ADD COLUMN shared BOOLEAN DEFAULT false;
    END IF;

    -- created_at
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'gastos' AND column_name = 'created_at'
    ) THEN
        ALTER TABLE public.gastos ADD COLUMN created_at TIMESTAMPTZ DEFAULT now();
    END IF;
END $$;

-- ============================================================
-- 3. MIGRAR TABELA: rendas
-- ============================================================

DO $$
BEGIN
    -- profile_id
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'rendas' AND column_name = 'profile_id'
    ) THEN
        ALTER TABLE public.rendas ADD COLUMN profile_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE;
    END IF;

    -- mes_ref
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'rendas' AND column_name = 'mes_ref'
    ) THEN
        ALTER TABLE public.rendas ADD COLUMN mes_ref TEXT DEFAULT to_char(now(), 'YYYY-MM');
    END IF;

    -- created_at
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'rendas' AND column_name = 'created_at'
    ) THEN
        ALTER TABLE public.rendas ADD COLUMN created_at TIMESTAMPTZ DEFAULT now();
    END IF;
END $$;

-- ============================================================
-- 4. MIGRAR TABELA: metas
-- ============================================================

DO $$
BEGIN
    -- profile_id
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'metas' AND column_name = 'profile_id'
    ) THEN
        ALTER TABLE public.metas ADD COLUMN profile_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE;
    END IF;

    -- joint_account_id
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'metas' AND column_name = 'joint_account_id'
    ) THEN
        ALTER TABLE public.metas ADD COLUMN joint_account_id UUID REFERENCES public.joint_accounts(id) ON DELETE SET NULL;
    END IF;

    -- created_at
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'metas' AND column_name = 'created_at'
    ) THEN
        ALTER TABLE public.metas ADD COLUMN created_at TIMESTAMPTZ DEFAULT now();
    END IF;
END $$;

-- ============================================================
-- 5. FUNÇÃO AUXILIAR para RLS
-- ============================================================

CREATE OR REPLACE FUNCTION public.my_joint_account_id()
RETURNS UUID
LANGUAGE sql
STABLE
SECURITY DEFINER
AS $$
    SELECT joint_account_id
    FROM public.profiles
    WHERE id = auth.uid();
$$;

-- ============================================================
-- 6. HABILITAR RLS em todas as tabelas
-- ============================================================

ALTER TABLE public.joint_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profiles       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gastos         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rendas         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.metas          ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 7. RLS POLICIES (remove anteriores para evitar conflito)
-- ============================================================

-- ─── profiles ───
DROP POLICY IF EXISTS "profiles_select" ON public.profiles;
DROP POLICY IF EXISTS "profiles_insert" ON public.profiles;
DROP POLICY IF EXISTS "profiles_update" ON public.profiles;

CREATE POLICY "profiles_select" ON public.profiles
    FOR SELECT USING (
        id = auth.uid()
        OR (joint_account_id IS NOT NULL AND joint_account_id = public.my_joint_account_id())
    );

CREATE POLICY "profiles_insert" ON public.profiles
    FOR INSERT WITH CHECK (id = auth.uid());

CREATE POLICY "profiles_update" ON public.profiles
    FOR UPDATE USING (id = auth.uid()) WITH CHECK (id = auth.uid());

-- ─── joint_accounts ───
DROP POLICY IF EXISTS "joint_accounts_select" ON public.joint_accounts;
DROP POLICY IF EXISTS "joint_accounts_insert" ON public.joint_accounts;
DROP POLICY IF EXISTS "joint_accounts_select_by_invite" ON public.joint_accounts;

CREATE POLICY "joint_accounts_select" ON public.joint_accounts
    FOR SELECT USING (true);

CREATE POLICY "joint_accounts_insert" ON public.joint_accounts
    FOR INSERT WITH CHECK (true);

-- ─── rendas ───
DROP POLICY IF EXISTS "rendas_select" ON public.rendas;
DROP POLICY IF EXISTS "rendas_insert" ON public.rendas;
DROP POLICY IF EXISTS "rendas_update" ON public.rendas;
DROP POLICY IF EXISTS "rendas_delete" ON public.rendas;

CREATE POLICY "rendas_select" ON public.rendas
    FOR SELECT USING (
        profile_id = auth.uid()
        OR (
            public.my_joint_account_id() IS NOT NULL
            AND profile_id IN (
                SELECT id FROM public.profiles
                WHERE joint_account_id = public.my_joint_account_id()
            )
        )
    );

CREATE POLICY "rendas_insert" ON public.rendas
    FOR INSERT WITH CHECK (profile_id = auth.uid());

CREATE POLICY "rendas_update" ON public.rendas
    FOR UPDATE USING (profile_id = auth.uid()) WITH CHECK (profile_id = auth.uid());

CREATE POLICY "rendas_delete" ON public.rendas
    FOR DELETE USING (profile_id = auth.uid());

-- ─── gastos ───
DROP POLICY IF EXISTS "gastos_select" ON public.gastos;
DROP POLICY IF EXISTS "gastos_insert" ON public.gastos;
DROP POLICY IF EXISTS "gastos_update" ON public.gastos;
DROP POLICY IF EXISTS "gastos_delete" ON public.gastos;

CREATE POLICY "gastos_select" ON public.gastos
    FOR SELECT USING (
        profile_id = auth.uid()
        OR (
            shared = true
            AND public.my_joint_account_id() IS NOT NULL
            AND profile_id IN (
                SELECT id FROM public.profiles
                WHERE joint_account_id = public.my_joint_account_id()
            )
        )
    );

CREATE POLICY "gastos_insert" ON public.gastos
    FOR INSERT WITH CHECK (profile_id = auth.uid());

CREATE POLICY "gastos_update" ON public.gastos
    FOR UPDATE USING (profile_id = auth.uid()) WITH CHECK (profile_id = auth.uid());

CREATE POLICY "gastos_delete" ON public.gastos
    FOR DELETE USING (profile_id = auth.uid());

-- ─── metas ───
DROP POLICY IF EXISTS "metas_select" ON public.metas;
DROP POLICY IF EXISTS "metas_insert" ON public.metas;
DROP POLICY IF EXISTS "metas_update" ON public.metas;
DROP POLICY IF EXISTS "metas_delete" ON public.metas;

CREATE POLICY "metas_select" ON public.metas
    FOR SELECT USING (
        profile_id = auth.uid()
        OR (
            joint_account_id IS NOT NULL
            AND joint_account_id = public.my_joint_account_id()
        )
    );

CREATE POLICY "metas_insert" ON public.metas
    FOR INSERT WITH CHECK (profile_id = auth.uid());

CREATE POLICY "metas_update" ON public.metas
    FOR UPDATE USING (profile_id = auth.uid()) WITH CHECK (profile_id = auth.uid());

CREATE POLICY "metas_delete" ON public.metas
    FOR DELETE USING (profile_id = auth.uid());

-- ============================================================
-- 8. TRIGGER: cria perfil automaticamente ao registrar
-- ============================================================

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, display_name)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data ->> 'display_name', NEW.email)
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

-- ============================================================
-- 9. ÍNDICES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_gastos_profile   ON public.gastos(profile_id);
CREATE INDEX IF NOT EXISTS idx_gastos_data      ON public.gastos(data_registro);
CREATE INDEX IF NOT EXISTS idx_gastos_shared    ON public.gastos(shared) WHERE shared = true;
CREATE INDEX IF NOT EXISTS idx_rendas_profile   ON public.rendas(profile_id);
CREATE INDEX IF NOT EXISTS idx_metas_profile    ON public.metas(profile_id);
CREATE INDEX IF NOT EXISTS idx_metas_joint      ON public.metas(joint_account_id) WHERE joint_account_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_profiles_joint   ON public.profiles(joint_account_id) WHERE joint_account_id IS NOT NULL;

-- ============================================================
-- 10. PERFIS-MEMBRO (sem login) — para cartão de crédito
--     compartilhado. Ex.: "Cartão da família" usado por várias
--     pessoas que não têm conta própria no app. Quem tem login
--     cadastra o membro e passa a poder marcar "quem comprou"
--     em cada gasto, sem precisar criar uma conta para cada um.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.membros (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id   UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    nome       TEXT NOT NULL,
    emoji      TEXT NOT NULL DEFAULT '🙂',
    cor        TEXT NOT NULL DEFAULT '#1B998B',
    ativo      BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Adiciona a referência ao membro em gastos (quem realmente comprou)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'gastos' AND column_name = 'membro_id'
    ) THEN
        ALTER TABLE public.gastos ADD COLUMN membro_id UUID REFERENCES public.membros(id) ON DELETE SET NULL;
    END IF;
END $$;

ALTER TABLE public.membros ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "membros_select" ON public.membros;
DROP POLICY IF EXISTS "membros_insert" ON public.membros;
DROP POLICY IF EXISTS "membros_update" ON public.membros;
DROP POLICY IF EXISTS "membros_delete" ON public.membros;

-- Visível para quem criou e para quem divide a mesma conta conjunta
CREATE POLICY "membros_select" ON public.membros
    FOR SELECT USING (
        owner_id = auth.uid()
        OR (
            public.my_joint_account_id() IS NOT NULL
            AND owner_id IN (
                SELECT id FROM public.profiles
                WHERE joint_account_id = public.my_joint_account_id()
            )
        )
    );

CREATE POLICY "membros_insert" ON public.membros
    FOR INSERT WITH CHECK (owner_id = auth.uid());

CREATE POLICY "membros_update" ON public.membros
    FOR UPDATE USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());

CREATE POLICY "membros_delete" ON public.membros
    FOR DELETE USING (owner_id = auth.uid());

CREATE INDEX IF NOT EXISTS idx_membros_owner  ON public.membros(owner_id);
CREATE INDEX IF NOT EXISTS idx_gastos_membro  ON public.gastos(membro_id) WHERE membro_id IS NOT NULL;
