import React, { useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, Image, Animated } from "react-native";
import { useWebSocket } from "../hooks/useWebSocket";
import ConnectionBadge from "../components/ConnectionBadge";
import type { ExitDisplayEvent, ExitBillEvent } from "../types";

interface Props {
  host: string;
  onBack: () => void;
}

function pad(n: number) {
  return n.toString().padStart(2, "0");
}

export default function ExitDisplayScreen({ host, onBack }: Props) {
  const wsUrl = `ws://${host}/ws/exit-display`;
  const { status, lastEvent } = useWebSocket<ExitDisplayEvent>(wsUrl);

  const [bill, setBill] = useState<ExitBillEvent | null>(null);
  const [showBarrier, setShowBarrier] = useState(false);
  const barrierAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!lastEvent) return;

    if (lastEvent.event === "exit_bill") {
      setBill(lastEvent);
    }

    if (lastEvent.event === "barrier_open" && lastEvent.gate === "exit") {
      setShowBarrier(true);
      Animated.sequence([
        Animated.timing(barrierAnim, { toValue: 1, duration: 200, useNativeDriver: true }),
        Animated.delay(2200),
        Animated.timing(barrierAnim, { toValue: 0, duration: 300, useNativeDriver: true }),
      ]).start(() => setShowBarrier(false));
    }

    if (lastEvent.event === "exit_clear") {
      setBill(null);
    }
  }, [lastEvent]);

  return (
    <View style={styles.container}>
      <View style={styles.topBar}>
        <ConnectionBadge status={status} />
        <TouchableOpacity onPress={onBack}>
          <Text style={styles.backLink}>Настройки</Text>
        </TouchableOpacity>
      </View>

      {bill ? (
        <View style={styles.billContainer}>
          <Text style={styles.plate}>{bill.plate_number}</Text>

          <View style={styles.row}>
            <View style={styles.infoBlock}>
              <Text style={styles.infoLabel}>Время на парковке</Text>
              <Text style={styles.infoValue}>
                {pad(bill.duration.hours)}:{pad(bill.duration.minutes)}:{pad(bill.duration.seconds)}
              </Text>
            </View>
            <View style={styles.infoBlock}>
              <Text style={styles.infoLabel}>К оплате</Text>
              <Text style={styles.amountValue}>{bill.amount_due.toFixed(2)} ₽</Text>
            </View>
          </View>

          <View style={styles.qrBox}>
            <Image source={{ uri: bill.qr_code_base64 }} style={styles.qrImage} />
            <Text style={styles.qrHint}>Отсканируйте QR-код для оплаты</Text>
            <Text style={styles.qrUrl}>{bill.pay_url}</Text>
          </View>
        </View>
      ) : (
        <View style={styles.waitingContainer}>
          <Text style={styles.waitingEmoji}>🚙</Text>
          <Text style={styles.waitingText}>Ожидание автомобиля на выезде…</Text>
        </View>
      )}

      {showBarrier && (
        <Animated.View
          style={[
            styles.barrierOverlay,
            {
              opacity: barrierAnim,
              transform: [
                {
                  scale: barrierAnim.interpolate({ inputRange: [0, 1], outputRange: [0.9, 1] }),
                },
              ],
            },
          ]}
        >
          <Text style={styles.barrierEmoji}>✅</Text>
          <Text style={styles.barrierText}>Оплата принята</Text>
          <Text style={styles.barrierSubtext}>Шлагбаум открыт, счастливого пути</Text>
        </Animated.View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0f172a", padding: 20 },
  topBar: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  backLink: { color: "#60a5fa", fontSize: 13 },

  waitingContainer: { flex: 1, alignItems: "center", justifyContent: "center" },
  waitingEmoji: { fontSize: 64, marginBottom: 16 },
  waitingText: { color: "#94a3b8", fontSize: 17 },

  billContainer: { flex: 1, paddingTop: 12 },
  plate: {
    alignSelf: "center",
    backgroundColor: "#111827",
    color: "#fff",
    fontSize: 22,
    fontWeight: "800",
    letterSpacing: 3,
    paddingHorizontal: 20,
    paddingVertical: 8,
    borderRadius: 10,
    marginBottom: 20,
  },
  row: { flexDirection: "row", gap: 14, marginBottom: 20 },
  infoBlock: {
    flex: 1,
    backgroundColor: "#1e293b",
    borderRadius: 16,
    padding: 18,
    alignItems: "center",
  },
  infoLabel: { color: "#94a3b8", fontSize: 13, fontWeight: "600", marginBottom: 8 },
  infoValue: { color: "#fff", fontSize: 28, fontWeight: "800" },
  amountValue: { color: "#4ade80", fontSize: 28, fontWeight: "800" },

  qrBox: {
    flex: 1,
    backgroundColor: "#fff",
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 20,
  },
  qrImage: { width: 200, height: 200 },
  qrHint: { color: "#111827", fontSize: 14, fontWeight: "700", marginTop: 14 },
  qrUrl: { color: "#6b7280", fontSize: 11, marginTop: 4 },

  barrierOverlay: {
    position: "absolute",
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: "rgba(15,23,42,0.97)",
    alignItems: "center",
    justifyContent: "center",
  },
  barrierEmoji: { fontSize: 56 },
  barrierText: { color: "#4ade80", fontSize: 26, fontWeight: "800", marginTop: 12 },
  barrierSubtext: { color: "#cbd5e1", fontSize: 14, marginTop: 8 },
});
