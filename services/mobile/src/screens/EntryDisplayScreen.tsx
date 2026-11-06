import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Animated,
  ScrollView,
  ActivityIndicator,
  useWindowDimensions,
} from "react-native";
import {
  SquareParking,
  Settings,
  Wifi,
  WifiOff,
  Clock,
  Gift,
  Ban,
  CircleCheck,
  TriangleAlert,
  ChevronsUp,
} from "lucide-react-native";
import { useWebSocket } from "../hooks/useWebSocket";
import type { ConnectionStatus } from "../hooks/useWebSocket";
import type { EntryDisplayEvent, EntryDisplayUpdateEvent } from "../types";
import { colors } from "../theme/entryTheme";
import { formatPrice, pluralRu, readAvailability, readTariff } from "../lib/parking";

interface Props {
  host: string;
  onBack: () => void;
}

const CONNECTION: Record<ConnectionStatus, { label: string; color: string }> = {
  connected: { label: "Онлайн", color: colors.free },
  connecting: { label: "Подключение…", color: colors.warn },
  disconnected: { label: "Нет связи", color: colors.full },
};

export default function EntryDisplayScreen({ host, onBack }: Props) {
  const wsUrl = `ws://${host}/ws/entry-display`;
  const { status, lastEvent } = useWebSocket<EntryDisplayEvent>(wsUrl);
  const { width } = useWindowDimensions();
  const compact = width < 360;

  const [state, setState] = useState<EntryDisplayUpdateEvent | null>(null);
  const [barrierPlate, setBarrierPlate] = useState<string | null>(null);
  const barrierAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!lastEvent) return;

    if (lastEvent.event === "entry_display_update") {
      setState(lastEvent);
    }

    if (lastEvent.event === "barrier_open" && lastEvent.gate === "entry") {
      setBarrierPlate(lastEvent.plate_number);
      Animated.sequence([
        Animated.timing(barrierAnim, { toValue: 1, duration: 200, useNativeDriver: true }),
        Animated.delay(2200),
        Animated.timing(barrierAnim, { toValue: 0, duration: 300, useNativeDriver: true }),
      ]).start(() => setBarrierPlate(null));
    }
  }, [lastEvent]);

  const availability = useMemo(() => (state ? readAvailability(state) : null), [state]);
  const tariff = useMemo(() => (state ? readTariff(state) : null), [state]);

  const isOnline = status === "connected";
  const isStale = !isOnline && availability !== null;

  const verdict = (() => {
    if (!availability) return null;
    if (isStale) {
      return { tone: "muted" as const, Icon: TriangleAlert, text: "Данные могут быть неактуальны" };
    }
    if (availability.isFull) {
      return { tone: "full" as const, Icon: Ban, text: "Мест нет — въезд недоступен" };
    }
    if (availability.free === 1) {
      return { tone: "warn" as const, Icon: CircleCheck, text: "Осталось последнее место" };
    }
    return { tone: "free" as const, Icon: CircleCheck, text: "Въезд открыт" };
  })();

  const toneColor = (tone: "free" | "warn" | "full" | "muted") =>
    tone === "free" ? colors.free : tone === "warn" ? colors.warn : tone === "full" ? colors.full : colors.textMuted;
  const toneSoft = (tone: "free" | "warn" | "full" | "muted") =>
    tone === "free" ? colors.freeSoft : tone === "warn" ? colors.warnSoft : tone === "full" ? colors.fullSoft : "transparent";

  const conn = CONNECTION[status];
  const ConnIcon = isOnline ? Wifi : WifiOff;

  return (
    <View style={styles.container}>
      <ScrollView
        contentContainerStyle={[styles.content, compact && styles.contentCompact]}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.inner}>
          {/* Header */}
          <View style={styles.header}>
            <View style={styles.titleRow}>
              <SquareParking size={22} color={colors.text} strokeWidth={1.75} />
              <Text style={styles.title}>Въезд</Text>
            </View>
            <TouchableOpacity
              onPress={onBack}
              style={styles.settingsBtn}
              hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
              accessibilityRole="button"
              accessibilityLabel="Настройки"
            >
              <Settings size={16} color={colors.textMuted} strokeWidth={1.75} />
              <Text style={styles.settingsText}>Настройки</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.connRow}>
            <ConnIcon size={14} color={conn.color} strokeWidth={2} />
            <Text style={[styles.connText, { color: conn.color }]}>{conn.label}</Text>
          </View>

          {/* Availability */}
          {availability && verdict ? (
            <View style={styles.card}>
              <Text style={styles.cardLabel}>Свободные места</Text>

              <View style={styles.countRow}>
                <Text
                  style={[
                    styles.countNumber,
                    compact && styles.countNumberCompact,
                    { color: isStale ? colors.textMuted : availability.isFull ? colors.full : colors.text },
                  ]}
                  accessibilityLabel={`Свободно ${availability.free} из ${availability.total}`}
                >
                  {availability.free}
                </Text>
                <Text style={styles.countTotal}>из {availability.total}</Text>
              </View>

              <View style={styles.pips} accessibilityElementsHidden>
                {Array.from({ length: availability.total }, (_, i) => {
                  const taken = i < availability.occupied;
                  return (
                    <View
                      key={i}
                      style={[
                        styles.pip,
                        taken
                          ? styles.pipTaken
                          : { backgroundColor: isStale ? colors.borderStrong : toneColor(verdict.tone) },
                      ]}
                    />
                  );
                })}
              </View>

              <View style={styles.legendRow}>
                <Text style={styles.legendText}>
                  Занято {availability.occupied} из {availability.total} мест
                </Text>
              </View>

              <View style={[styles.verdict, { backgroundColor: toneSoft(verdict.tone) }]}>
                <verdict.Icon size={16} color={toneColor(verdict.tone)} strokeWidth={2} />
                <Text style={[styles.verdictText, { color: toneColor(verdict.tone) }]}>
                  {verdict.text}
                </Text>
              </View>
            </View>
          ) : state ? (
            // Payload arrived but is not usable
            <View style={[styles.card, styles.centerCard]}>
              <TriangleAlert size={26} color={colors.warn} strokeWidth={1.75} />
              <Text style={styles.stateTitle}>Некорректные данные</Text>
              <Text style={styles.stateText}>
                Сервер прислал неожиданный ответ о местах. Ожидаем следующее обновление.
              </Text>
            </View>
          ) : status === "disconnected" ? (
            <View style={[styles.card, styles.centerCard]}>
              <WifiOff size={26} color={colors.full} strokeWidth={1.75} />
              <Text style={styles.stateTitle}>Нет связи с сервером</Text>
              <Text style={styles.stateText}>Повторное подключение к {host}…</Text>
            </View>
          ) : (
            <View style={[styles.card, styles.centerCard]}>
              <ActivityIndicator color={colors.textMuted} />
              <Text style={styles.stateText}>Загрузка данных о местах…</Text>
            </View>
          )}

          {/* Tariff */}
          <View style={styles.card}>
            <Text style={styles.cardLabel}>Тариф</Text>
            {tariff ? (
              <>
                <Text style={styles.tariffName} numberOfLines={2}>
                  {tariff.name}
                </Text>
                <View style={styles.priceRow}>
                  <Text style={styles.priceValue}>{formatPrice(tariff.price_per_minute)}</Text>
                  <Text style={styles.priceUnit}> сом / мин</Text>
                </View>
                <View style={styles.divider} />
                <View style={styles.infoRow}>
                  {tariff.free_minutes > 0 ? (
                    <>
                      <Gift size={15} color={colors.textMuted} strokeWidth={1.75} />
                      <Text style={styles.infoText}>
                        Первые {tariff.free_minutes}{" "}
                        {pluralRu(tariff.free_minutes, "минута", "минуты", "минут")} бесплатно
                      </Text>
                    </>
                  ) : (
                    <>
                      <Clock size={15} color={colors.textMuted} strokeWidth={1.75} />
                      <Text style={styles.infoText}>Оплата со времени въезда</Text>
                    </>
                  )}
                </View>
              </>
            ) : state ? (
              <Text style={styles.stateText}>Тариф не задан</Text>
            ) : (
              <Text style={styles.stateText}>Загрузка тарифа…</Text>
            )}
          </View>
        </View>
      </ScrollView>

      {barrierPlate && (
        <Animated.View
          pointerEvents="none"
          style={[
            styles.barrierOverlay,
            {
              opacity: barrierAnim,
              transform: [
                { scale: barrierAnim.interpolate({ inputRange: [0, 1], outputRange: [0.96, 1] }) },
              ],
            },
          ]}
        >
          <View style={styles.barrierIcon}>
            <ChevronsUp size={36} color={colors.free} strokeWidth={1.75} />
          </View>
          <Text style={styles.barrierText}>Шлагбаум открыт</Text>
          <Text style={styles.barrierPlate}>{barrierPlate}</Text>
        </Animated.View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  content: { flexGrow: 1, padding: 20, alignItems: "center" },
  contentCompact: { padding: 14 },
  inner: { width: "100%", maxWidth: 520, gap: 14 },

  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  title: { color: colors.text, fontSize: 22, fontWeight: "700", letterSpacing: -0.2 },
  settingsBtn: { flexDirection: "row", alignItems: "center", gap: 6 },
  settingsText: { color: colors.textMuted, fontSize: 13, fontWeight: "500" },

  connRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: -4 },
  connText: { fontSize: 12, fontWeight: "600" },

  card: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    padding: 20,
  },
  centerCard: { alignItems: "center", gap: 10, paddingVertical: 32 },
  cardLabel: {
    color: colors.textMuted,
    fontSize: 13,
    fontWeight: "600",
    marginBottom: 12,
  },

  countRow: { flexDirection: "row", alignItems: "baseline", gap: 10 },
  countNumber: { fontSize: 72, fontWeight: "700", lineHeight: 78, letterSpacing: -2 },
  countNumberCompact: { fontSize: 58, lineHeight: 64 },
  countTotal: { color: colors.textMuted, fontSize: 20, fontWeight: "500" },

  pips: { flexDirection: "row", gap: 8, marginTop: 16 },
  pip: { flex: 1, height: 6, borderRadius: 3 },
  pipTaken: { backgroundColor: colors.borderStrong },

  legendRow: { marginTop: 10 },
  legendText: { color: colors.textFaint, fontSize: 12 },

  verdict: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 16,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 10,
  },
  verdictText: { fontSize: 14, fontWeight: "600", flexShrink: 1 },

  stateTitle: { color: colors.text, fontSize: 16, fontWeight: "600" },
  stateText: { color: colors.textMuted, fontSize: 13, textAlign: "center", lineHeight: 19 },

  tariffName: { color: colors.textMuted, fontSize: 14, marginBottom: 8 },
  priceRow: { flexDirection: "row", alignItems: "baseline" },
  priceValue: { color: colors.text, fontSize: 38, fontWeight: "700", letterSpacing: -1 },
  priceUnit: { color: colors.textMuted, fontSize: 16, fontWeight: "500" },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: 14 },
  infoRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  infoText: { color: colors.textMuted, fontSize: 13, flexShrink: 1 },

  barrierOverlay: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(15,23,42,0.96)",
    alignItems: "center",
    justifyContent: "center",
  },
  barrierIcon: {
    width: 72,
    height: 72,
    borderRadius: 36,
    borderWidth: 1,
    borderColor: colors.freeSoft,
    backgroundColor: colors.freeSoft,
    alignItems: "center",
    justifyContent: "center",
  },
  barrierText: { color: colors.text, fontSize: 22, fontWeight: "700", marginTop: 16 },
  barrierPlate: { color: colors.textMuted, fontSize: 16, marginTop: 8, letterSpacing: 2 },
});
