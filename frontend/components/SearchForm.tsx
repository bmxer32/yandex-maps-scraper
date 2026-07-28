"use client";

import { useMemo, useState } from "react";
import { Search, Loader2, MapPin, Building2, Train } from "lucide-react";
import type { GeoNode, SearchRequest } from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Select,
  Slider,
  Switch,
} from "@/components/ui";

/* Частые категории для быстрого выбора */
const POPULAR_CATEGORIES = [
  "Стоматологии",
  "Автосервисы",
  "Рестораны",
  "Бары",
  "Барбершопы",
  "Салоны красоты",
  "Юридические услуги",
  "Фитнес-клубы",
  "Цветочные магазины",
  "Ветеринарные клиники",
  "Школы английского",
  "Ремонт квартир",
];

interface SearchFormProps {
  geoTree: GeoNode[];
  loading: boolean;
  onSubmit: (req: SearchRequest) => void;
  disabled?: boolean;
}

export function SearchForm({ geoTree, loading, onSubmit, disabled }: SearchFormProps) {
  const [category, setCategory] = useState("");
  const [regionId, setRegionId] = useState("");
  const [cityId, setCityId] = useState("");
  const [districtId, setDistrictId] = useState("");
  const [metroId, setMetroId] = useState("");
  const [limit, setLimit] = useState(500);
  const [fetchWebsites, setFetchWebsites] = useState(true);
  const [enrichSites, setEnrichSites] = useState(true);

  // Каскадная фильтрация гео-дерева
  const regions = useMemo(
    () => geoTree.filter((n) => n.level === "region" && n.parent_id === "ru"),
    [geoTree],
  );
  const cities = useMemo(
    () => geoTree.filter((n) => n.level === "city" && n.parent_id === regionId),
    [geoTree, regionId],
  );
  const districts = useMemo(
    () => geoTree.filter((n) => n.level === "district" && n.parent_id === cityId),
    [geoTree, cityId],
  );
  const metros = useMemo(
    () => geoTree.filter((n) => n.level === "metro" && n.parent_id === cityId),
    [geoTree, cityId],
  );

  // Сброс дочерних селекторов при смене родителя
  function handleRegionChange(id: string) {
    setRegionId(id);
    setCityId("");
    setDistrictId("");
    setMetroId("");
  }
  function handleCityChange(id: string) {
    setCityId(id);
    setDistrictId("");
    setMetroId("");
  }

  const canSubmit = category.trim().length >= 2 && !!regionId && !disabled;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      category: category.trim(),
      country_id: "ru",
      region_id: regionId || null,
      city_id: cityId || null,
      district_id: districtId || null,
      metro_id: metroId || null,
      limit,
      fetch_websites: fetchWebsites,
      enrich_sites: enrichSites,
    });
  }

  return (
    <Card className="animate-fade-in">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Search className="h-5 w-5" />
          </div>
          <div>
            <CardTitle>Параметры поиска</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Сфера и локация — остальное подгрузится автоматически
            </p>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Сфера */}
          <div className="space-y-2">
            <label htmlFor="category" className="text-sm font-medium">
              Сфера / рубрика
            </label>
            <Input
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="Например: стоматологии, автосервисы, бары…"
              list="category-suggestions"
            />
            <datalist id="category-suggestions">
              {POPULAR_CATEGORIES.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
            {/* Чипы быстрых категорий */}
            <div className="flex flex-wrap gap-1.5 pt-1">
              {POPULAR_CATEGORIES.slice(0, 6).map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setCategory(c)}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-xs transition-colors",
                    category === c
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/30 hover:text-foreground",
                  )}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>

          {/* Гео: регион → город */}
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <label className="flex items-center gap-1.5 text-sm font-medium">
                <MapPin className="h-3.5 w-3.5 text-muted-foreground" />
                Область / край
              </label>
              <Select
                value={regionId}
                onChange={handleRegionChange}
                options={regions.map((r) => ({ value: r.id, label: r.name }))}
                placeholder="Выберите регион…"
              />
            </div>
            <div className="space-y-2">
              <label className="flex items-center gap-1.5 text-sm font-medium">
                <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                Город
              </label>
              <Select
                value={cityId}
                onChange={handleCityChange}
                options={cities.map((c) => ({ value: c.id, label: c.name }))}
                placeholder="Сначала выберите регион"
                disabled={!regionId}
              />
            </div>
          </div>

          {/* Район / метро (только для городов, где есть) */}
          {(districts.length > 0 || metros.length > 0) && (
            <div className="grid gap-4 sm:grid-cols-2">
              {districts.length > 0 && (
                <div className="space-y-2">
                  <label className="flex items-center gap-1.5 text-sm font-medium">
                    <MapPin className="h-3.5 w-3.5 text-muted-foreground" />
                    Район
                  </label>
                  <Select
                    value={districtId}
                    onChange={setDistrictId}
                    options={districts.map((d) => ({ value: d.id, label: d.name }))}
                    placeholder="Любой район"
                  />
                </div>
              )}
              {metros.length > 0 && (
                <div className="space-y-2">
                  <label className="flex items-center gap-1.5 text-sm font-medium">
                    <Train className="h-3.5 w-3.5 text-muted-foreground" />
                    Метро
                  </label>
                  <Select
                    value={metroId}
                    onChange={setMetroId}
                    options={metros.map((m) => ({ value: m.id, label: m.name }))}
                    placeholder="Любая станция"
                  />
                </div>
              )}
            </div>
          )}

          {/* Лимит + переключатель */}
          <div className="grid gap-5 sm:grid-cols-2">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium">Сколько собирать</label>
                <span className="font-mono text-sm text-primary">
                  {formatNumber(limit)}
                </span>
              </div>
              <Slider
                value={limit}
                min={50}
                max={1000}
                step={50}
                onChange={setLimit}
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>50</span>
                <span>1000</span>
              </div>
            </div>

            <div className="space-y-3 rounded-md border border-border bg-secondary/30 p-3">
              <Switch
                checked={fetchWebsites}
                onChange={setFetchWebsites}
                label="Сайты и соцсети из Яндекс.Карт"
                description="Открывает карточку каждой организации (~2 сек на карточку). Без этого сайты не собираются."
              />
              <div className="h-px bg-border/60" />
              <Switch
                checked={enrichSites}
                onChange={setEnrichSites}
                label="Email и соцсети с сайтов"
                description="Второй проход: открывает сайт каждой организации и достаёт контакты"
              />
            </div>
          </div>

          {/* Submit */}
          <div className="flex items-center gap-3 pt-2">
            <Button
              type="submit"
              size="lg"
              disabled={!canSubmit || loading}
              className="flex-1 sm:flex-none"
            >
              {loading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Запускаю…
                </>
              ) : (
                <>
                  <Search className="h-4 w-4" />
                  Собрать данные
                </>
              )}
            </Button>
            {!canSubmit && (
              <p className="text-xs text-muted-foreground">
                Заполните сферу и выберите регион
              </p>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
