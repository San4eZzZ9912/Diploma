package com.diploma.robot_warehouse_backend.entity;

import com.diploma.robot_warehouse_backend.enums.Status;
import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.LocalDateTime;
import java.util.List;

@Entity
@Getter
@Table(name = "outbounds")
@NoArgsConstructor
public class Outbound {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "outbound_id")
    private Integer id;

    @Column(name = "external_ref")
    private String externalRef;

    @Enumerated(EnumType.STRING)
    @Setter
    @Column(name = "status", nullable = false)
    private Status status;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @OneToMany(mappedBy = "outbound")
    private List<OutboundLine> outboundLines;

    public Outbound(String externalRef, Status status) {
        this.externalRef = externalRef;
        this.status = status;
        this.createdAt = LocalDateTime.now();
    }
}
