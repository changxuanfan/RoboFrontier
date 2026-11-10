"""Robot-only inverse kinematics on a fixed-base kinematic chain."""
import xml.etree.ElementTree as ET

import mujoco
import numpy as np


class RobotIK:
    """Damped least squares; only robot joint coordinates enter this solver.

    The kinematic scratch model contains only the fixed-base chain ending at
    this robot's TCP. No environment bodies, contacts or object poses enter FK.
    """
    def __init__(self, model, prefix=""):
        self.model = model
        self.joints = np.array([model.joint(f"{prefix}joint{i}").id for i in range(1, 8)])
        self.qids = model.jnt_qposadr[self.joints]
        self.dofs = model.jnt_dofadr[self.joints]
        self.site = model.site(f"{prefix}tcp").id
        self.limits = model.jnt_range[self.joints].copy()
        for i in range(7):
            actuator = model.actuator(f"{prefix}actuator{i+1}").id
            self.limits[i, 0] = max(self.limits[i, 0], model.actuator_ctrlrange[actuator, 0]) + 0.02
            self.limits[i, 1] = min(self.limits[i, 1], model.actuator_ctrlrange[actuator, 1]) - 0.02
        root=ET.Element('mujoco');ET.SubElement(root,'compiler',angle='radian',autolimits='true');world=ET.SubElement(root,'worldbody')
        body=int(model.site_bodyid[self.site]);chain=[]
        while body:chain.append(body);body=int(model.body_parentid[body])
        def numbers(values):return ' '.join(repr(float(x)) for x in values)
        parent=world;copied=set()
        for body in reversed(chain):
            parent=ET.SubElement(parent,'body',name=model.body(body).name,pos=numbers(model.body_pos[body]),quat=numbers(model.body_quat[body]))
            if model.body_mass[body]>0:ET.SubElement(parent,'inertial',mass=str(model.body_mass[body]),pos=numbers(model.body_ipos[body]),quat=numbers(model.body_iquat[body]),diaginertia=numbers(model.body_inertia[body]))
            for joint in range(model.body_jntadr[body],model.body_jntadr[body]+model.body_jntnum[body]):
                if joint not in self.joints or model.jnt_type[joint]!=mujoco.mjtJoint.mjJNT_HINGE:raise ValueError('RobotIK requires a fixed-base seven-hinge chain')
                ET.SubElement(parent,'joint',name=model.joint(joint).name,type='hinge',axis=numbers(model.jnt_axis[joint]),pos=numbers(model.jnt_pos[joint]),range=numbers(model.jnt_range[joint]),ref=str(model.qpos0[model.jnt_qposadr[joint]]));copied.add(joint)
        if copied!=set(self.joints):raise ValueError('Robot TCP does not descend from every arm joint')
        ET.SubElement(parent,'site',name=prefix+'tcp',pos=numbers(model.site_pos[self.site]),quat=numbers(model.site_quat[self.site]))
        self.kinematic_model=mujoco.MjModel.from_xml_string(ET.tostring(root,encoding='unicode'));self.data=mujoco.MjData(self.kinematic_model)
        local_joints=[self.kinematic_model.joint(model.joint(int(j)).name).id for j in self.joints]
        self.local_qids=self.kinematic_model.jnt_qposadr[local_joints];self.local_dofs=self.kinematic_model.jnt_dofadr[local_joints];self.local_site=self.kinematic_model.site(prefix+'tcp').id
        self.jp = np.zeros((3, self.kinematic_model.nv))
        self.jr = np.zeros((3, self.kinematic_model.nv))

    def pose(self, q):
        self.data.qpos[self.local_qids] = q
        mujoco.mj_kinematics(self.kinematic_model, self.data)
        mujoco.mj_comPos(self.kinematic_model, self.data)
        return self.data.site_xpos[self.local_site].copy(), self.data.site_xmat[self.local_site].reshape(3, 3).copy()

    def solve(self, target, rotation, seed, iterations=20):
        q = seed.copy()
        for _ in range(iterations):
            position, current_r = self.pose(q)
            # Quaternion log remains informative at a 180-degree rotation.
            quat = np.empty(4)
            mujoco.mju_mat2Quat(quat, (rotation @ current_r.T).ravel())
            if quat[0] < 0: quat = -quat
            sine = np.linalg.norm(quat[1:])
            rot_error = (np.zeros(3) if sine < 1e-12 else
                         quat[1:] * (2*np.arctan2(sine, max(0., quat[0])) / sine))
            error = np.r_[target - position, 0.35 * rot_error]
            if np.linalg.norm(error[:3]) < 0.00008 and np.linalg.norm(rot_error) < 0.0005:
                break
            mujoco.mj_jacSite(self.kinematic_model, self.data, self.jp, self.jr, self.local_site)
            jac = np.vstack([self.jp[:, self.local_dofs], 0.35 * self.jr[:, self.local_dofs]])
            delta = jac.T @ np.linalg.solve(jac @ jac.T + 0.012**2 * np.eye(6), error)
            delta *= min(1.0, 0.08 / max(np.max(np.abs(delta)), 1e-12))
            q = np.clip(q + delta, self.limits[:, 0], self.limits[:, 1])
        position, _ = self.pose(q)
        return q, float(np.linalg.norm(target - position))

